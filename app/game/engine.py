"""Match engine — the state machine that drives a single Gwent match.

Lifecycle:
    1. Match.create(...) builds PlayerState objects from deck card ids.
    2. start_match() deals opening hands (10 cards each) and starts round 1.
    3. play_card(player, card_instance, target_row=None) executes a card play
       and runs all on_played effects.
    4. pass(player) marks the player as passed.
    5. When all players have passed (or only one remains), the round ends:
       highest strength wins the round. Round counter advances; if no one has
       reached majority the match continues, otherwise match ends.
    6. Surrender forfeits the match for one player.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

from app.game.board import Board
from app.game.card_instance import CardInstance
from app.game.effects import EFFECT_REGISTRY, EffectContext
from app.game.player_state import PlayerState
from app.models.card import Card, CardType, Row


class MatchPhase(str, Enum):
    CREATED = "created"
    IN_PROGRESS = "in_progress"
    ROUND_END = "round_end"
    FINISHED = "finished"


class MatchError(RuntimeError):
    pass


# Type for an async event listener (e.g. the Discord UI layer subscribes to push updates).
EventListener = Callable[["Match", str, dict], Awaitable[None]]


@dataclass
class Match:
    match_id: str
    channel_id: int
    rounds_total: int = 3  # BO3 by default
    players: list[PlayerState] = field(default_factory=list)
    board: Board = field(default_factory=Board)
    phase: MatchPhase = MatchPhase.CREATED
    current_round: int = 0
    starting_player_index: int = 0
    current_player_index: int = 0
    log: list[str] = field(default_factory=list)
    winner: PlayerState | None = None
    card_lookup: dict[str, Card] = field(default_factory=dict)
    _listeners: list[EventListener] = field(default_factory=list)

    # --------------------------------------------------------- construction
    @classmethod
    def create(
        cls,
        channel_id: int,
        participants: list[tuple[int, str, str, list[str], str | None]],
        card_lookup: dict[str, Card],
        rounds_total: int = 3,
    ) -> "Match":
        """Build a fresh match.

        participants: list of (discord_id, display_name, faction_id, card_ids, leader_card_id).
        card_lookup: id -> Card mapping for all cards referenced.
        """
        match_id = uuid.uuid4().hex[:10]
        players: list[PlayerState] = []
        for discord_id, name, faction_id, card_ids, leader_id in participants:
            ps = PlayerState(discord_id=discord_id, display_name=name, faction_id=faction_id)
            ps.build_from_card_ids(card_ids, card_lookup, leader_id)
            players.append(ps)
        m = cls(
            match_id=match_id,
            channel_id=channel_id,
            rounds_total=rounds_total,
            players=players,
            card_lookup=card_lookup,
        )
        for p in players:
            m.board.init_player(p.discord_id)
        return m

    # --------------------------------------------------------- listeners
    def add_listener(self, listener: EventListener) -> None:
        self._listeners.append(listener)

    async def _emit(self, event: str, payload: dict | None = None) -> None:
        payload = payload or {}
        for listener in list(self._listeners):
            try:
                await listener(self, event, payload)
            except Exception as e:  # pragma: no cover
                self.log.append(f"[listener error] {e}")

    # --------------------------------------------------------- start
    async def start_match(self) -> None:
        if self.phase != MatchPhase.CREATED:
            raise MatchError("Match already started.")
        # Deal 10 cards to each player (classic Gwent opening hand size).
        for p in self.players:
            p.draw(10)
        self.current_round = 1
        self.starting_player_index = 0
        self.current_player_index = 0
        self.phase = MatchPhase.IN_PROGRESS
        self.log.append("Матч начался. Каждому игроку роздано по 10 карт.")
        await self._emit("match_started", {"round": self.current_round})

    # --------------------------------------------------------- queries
    @property
    def current_player(self) -> PlayerState:
        return self.players[self.current_player_index]

    def get_player(self, discord_id: int) -> PlayerState | None:
        for p in self.players:
            if p.discord_id == discord_id:
                return p
        return None

    def is_player_turn(self, discord_id: int) -> bool:
        return self.current_player.discord_id == discord_id

    def players_still_playing(self) -> list[PlayerState]:
        return [p for p in self.players if not p.passed]

    def all_passed(self) -> bool:
        """A round ends only when ALL players have passed. Players who haven't
        passed yet can keep playing cards even if everyone else has passed."""
        return all(p.passed for p in self.players)

    def all_passed_or_one_left(self) -> bool:
        # Kept for backward compatibility — same as all_passed in current rules.
        return self.all_passed()

    # --------------------------------------------------------- actions
    async def play_card(
        self,
        discord_id: int,
        instance_id: str,
        target_row: str | None = None,
    ) -> None:
        import logging as _log
        _logger = _log.getLogger("app.game.engine")
        _logger.info(
            "play_card called: discord_id=%s instance_id=%s target_row=%s phase=%s current_player=%s",
            discord_id, instance_id, target_row, self.phase.value, self.current_player.discord_id,
        )
        if self.phase != MatchPhase.IN_PROGRESS:
            raise MatchError(f"Cannot play card in phase {self.phase}.")
        player = self.get_player(discord_id)
        if player is None:
            raise MatchError("Unknown player.")
        if not self.is_player_turn(discord_id):
            raise MatchError(f"Not your turn — current player is {self.current_player.display_name}.")
        if player.passed:
            raise MatchError("You have already passed this round.")

        ci = player.play_from_hand(instance_id)
        if ci is None:
            raise MatchError("Card not in hand.")

        # Determine target row
        chosen_row = self._resolve_row(ci, target_row)
        if ci.card.is_unit:
            if chosen_row is None:
                raise MatchError("Unit card requires a target row.")
            self.board.add_unit(player.discord_id, chosen_row, ci)
        elif ci.card.is_weather:
            # Weather cards don't go on the board as units
            ci.location = "discard"
            player.discard.append(ci)
        elif ci.card.type == CardType.SPECIAL:
            # Specials (scorch, decoy, clear weather) go to discard immediately after resolving
            ci.location = "discard"
            player.discard.append(ci)
        else:
            # Leader cards are never "played" from hand — handled separately via use_leader.
            raise MatchError("This card type cannot be played directly.")

        # Build effect context
        ctx = EffectContext(
            match=self,
            board=self.board,
            player=player,
            card_instance=ci,
            target_row=chosen_row,
            log=self.log,
        )

        # Run effects
        for spec in ci.card.effects:
            try:
                effect = EFFECT_REGISTRY.build(spec.type, spec.params)
                await effect.on_played(ctx)
            except Exception as e:
                self.log.append(f"[effect error] {spec.type}: {e}")

        await self._emit(
            "card_played",
            {
                "player_id": discord_id,
                "card_id": ci.card.id,
                "card_name": ci.card.name,
                "row": chosen_row,
                "log": list(ctx.log),
            },
        )

        # Advance turn
        await self._advance_turn()

    async def use_leader(self, discord_id: int) -> None:
        player = self.get_player(discord_id)
        if player is None or player.leader_card is None:
            raise MatchError("No leader available.")
        if player.leader_used_this_round:
            raise MatchError("Leader ability already used this round.")
        if not self.is_player_turn(discord_id):
            raise MatchError("Not your turn.")
        player.leader_used_this_round = True
        # Apply faction ability (described in faction metadata, implemented per-faction)
        await self._apply_leader_ability(player)
        await self._emit("leader_used", {"player_id": discord_id, "faction": player.faction_id})
        await self._advance_turn()

    async def pass_turn(self, discord_id: int) -> None:
        player = self.get_player(discord_id)
        if player is None:
            raise MatchError("Unknown player.")
        if not self.is_player_turn(discord_id):
            raise MatchError("Not your turn.")
        if player.passed:
            raise MatchError("Already passed.")
        player.pass_round()
        self.log.append(f"{player.display_name} пасует.")
        await self._emit("player_passed", {"player_id": discord_id})

        if self.all_passed_or_one_left():
            await self._end_round()
        else:
            await self._advance_turn()

    async def surrender(self, discord_id: int) -> None:
        player = self.get_player(discord_id)
        if player is None:
            return
        # The surrendering player loses; if multiple opponents, the one with most strength wins.
        candidates = [p for p in self.players if p.discord_id != discord_id]
        if candidates:
            self.winner = max(candidates, key=lambda p: self.board.player_strength(p.discord_id))
        self.phase = MatchPhase.FINISHED
        self.log.append(f"{player.display_name} сдался. Победитель: {self.winner.display_name if self.winner else '—'}.")
        await self._emit("match_finished", {"winner_id": self.winner.discord_id if self.winner else None})

    # --------------------------------------------------------- internal
    def _resolve_row(self, ci: CardInstance, target_row: str | None) -> str | None:
        if not ci.card.is_unit:
            return None
        if ci.card.row is None:
            return None
        if ci.card.row == Row.AGILE:
            if target_row not in (Row.MELEE.value, Row.RANGED.value):
                raise MatchError("Agile unit must be played in melee or ranged.")
            return target_row
        if target_row and target_row != ci.card.row.value:
            raise MatchError(
                f"Card must be played in row {ci.card.row.value}, not {target_row}."
            )
        return ci.card.row.value

    async def _advance_turn(self) -> None:
        if self.all_passed_or_one_left():
            await self._end_round()
            return
        # Move to next non-passed player
        n = len(self.players)
        for offset in range(1, n + 1):
            idx = (self.current_player_index + offset) % n
            if not self.players[idx].passed:
                self.current_player_index = idx
                break
        await self._emit("turn_changed", {"current_player_id": self.current_player.discord_id})

    async def _end_round(self) -> None:
        # Determine round winner: highest board strength among non-passed... actually
        # in Gwent, even passed players count their strength. Highest wins. Tie = draw.
        strengths = {p.discord_id: self.board.player_strength(p.discord_id) for p in self.players}
        max_str = max(strengths.values())
        round_winners = [p for p in self.players if strengths[p.discord_id] == max_str]

        if len(round_winners) == 1:
            round_winners[0].rounds_won += 1
            winner_name = round_winners[0].display_name
            self.log.append(f"Раунд {self.current_round}: победил {winner_name} ({max_str} очков).")
        else:
            # Draw round — both get a win in Gwent classic rules
            for p in round_winners:
                p.rounds_won += 1
            self.log.append(f"Раунд {self.current_round}: ничья между {len(round_winners)} игроками.")

        await self._emit("round_ended", {
            "round": self.current_round,
            "strengths": strengths,
            "winners": [p.discord_id for p in round_winners],
        })

        # Check match end
        majority = (self.rounds_total // 2) + 1
        winners_match = [p for p in self.players if p.rounds_won >= majority]
        if winners_match or self.current_round >= self.rounds_total:
            await self._finish_match(winners_match or round_winners)
            return

        # Otherwise start next round
        self.current_round += 1
        # Player who lost the round starts next (classic Gwent rule).
        # If draw, the previous starting player keeps the turn.
        if len(round_winners) == 1:
            loser_index = next(
                i for i, p in enumerate(self.players) if p.discord_id != round_winners[0].discord_id
            )
            self.starting_player_index = loser_index
        self.current_player_index = self.starting_player_index

        # Reset round state
        for p in self.players:
            # Move all board units to discard (they don't come back)
            for row_units in self.board.rows[p.discord_id].values():
                for u in row_units:
                    u.location = "discard"
                    u.row = None
                    u.bonus_strength = 0
                    u.weathered = False
                    p.discard.append(u)
            p.reset_for_new_round()
        self.board.reset_for_new_round()

        # Each player draws 1-2 extra cards (Gwent rule: +2 cards in round 2, +1 in round 3)
        extra = 2 if self.current_round == 2 else 1 if self.current_round == 3 else 0
        for p in self.players:
            p.draw(extra)

        self.phase = MatchPhase.IN_PROGRESS
        await self._emit("round_started", {"round": self.current_round})

    async def _finish_match(self, winners: list[PlayerState]) -> None:
        if len(winners) == 1:
            self.winner = winners[0]
        else:
            # Final tie: highest total strength across all rounds wins
            self.winner = max(self.players, key=lambda p: self.board.player_strength(p.discord_id))
        self.phase = MatchPhase.FINISHED
        self.log.append(
            f"Матч завершён. Победитель: {self.winner.display_name if self.winner else '—'}."
        )
        await self._emit("match_finished", {
            "winner_id": self.winner.discord_id if self.winner else None,
            "final_rounds": {p.discord_id: p.rounds_won for p in self.players},
        })

    async def _apply_leader_ability(self, player: PlayerState) -> None:
        """Apply the active player's faction leader ability.

        Abilities are described in faction JSON (`ability_name` / `ability_desc`).
        Their mechanical implementation lives here, dispatched by faction_id.
        """
        faction_id = player.faction_id
        ctx = EffectContext(
            match=self,
            board=self.board,
            player=player,
            card_instance=None,  # type: ignore[arg-type]
            log=self.log,
        )

        if faction_id == "iron_legion":
            # Double strength of all friendly siege machines
            for unit in self.board.units_in_row(player.discord_id, Row.SIEGE.value):
                if not unit.card.hero:
                    unit.bonus_strength += unit.card.base_strength  # doubles base
            self.log.append(f"{player.display_name} применил «Железный строй».")

        elif faction_id == "verdant_coven":
            # Destroy the strongest enemy melee unit (heroes immune)
            opponents = [p for p in self.players if p.discord_id != player.discord_id]
            candidates: list[tuple[int, CardInstance]] = []
            for opp in opponents:
                for u in self.board.units_in_row(opp.discord_id, Row.MELEE.value):
                    if not u.card.hero:
                        candidates.append((opp.discord_id, u))
            if candidates:
                max_s = max(u.current_strength for _, u in candidates)
                victims = [(pid, u) for pid, u in candidates if u.current_strength == max_s]
                for pid, u in victims:
                    self.board.remove_unit(pid, Row.MELEE.value, u)
                    self.get_player(pid).discard.append(u)
                self.log.append(f"{player.display_name} применил «Гнев леса».")
            else:
                self.log.append("«Гнев леса» не нашёл целей.")

        elif faction_id == "ashen_pact":
            # Clear weather + deal 1 damage to each enemy unit (reduce bonus_strength by 1, floor at 0)
            self.board.clear_all_weather()
            opponents = [p for p in self.players if p.discord_id != player.discord_id]
            damaged = 0
            for opp in opponents:
                for u in self.board.all_units_for(opp.discord_id):
                    if not u.card.hero:
                        u.bonus_strength -= 1
                        damaged += 1
            self.log.append(f"{player.display_name} применил «Огненный шквал» (пострадало {damaged} единиц).")

        else:
            self.log.append(f"У фракции «{faction_id}» нет активной способности лидера.")

    # --------------------------------------------------------- snapshot
    def snapshot(self, viewer_discord_id: int | None = None) -> dict[str, Any]:
        """Return a JSON-serialisable snapshot for Discord/web rendering.

        If `viewer_discord_id` is provided, that player's hand is included
        (with full card details). Other players' hands are obscured (only
        card count is exposed).

        **IMPORTANT**: `discord_id` fields are returned as **strings**,
        not ints. Discord snowflake IDs are 18-digit numbers that exceed
        JavaScript's `Number.MAX_SAFE_INTEGER` (2^53 - 1), so passing them
        as JSON numbers causes precision loss in the browser and breaks
        identity comparison (msg.you !== player.discord_id).
        """
        return {
            "match_id": self.match_id,
            "phase": self.phase.value,
            "round": self.current_round,
            "rounds_total": self.rounds_total,
            "current_player_id": str(self.current_player.discord_id),
            "players": [
                {
                    "discord_id": str(p.discord_id),
                    "name": p.display_name,
                    "faction_id": p.faction_id,
                    "rounds_won": p.rounds_won,
                    "passed": p.passed,
                    "hand_size": p.hand_size,
                    "deck_size": p.deck_size,
                    "leader_used_this_round": p.leader_used_this_round,
                    "leader_name": p.leader_card.name if p.leader_card else None,
                    "leader_card_id": p.leader_card.id if p.leader_card else None,
                    "leader_image": p.leader_card.image_url() if p.leader_card else None,
                    "total_strength": self.board.player_strength(p.discord_id),
                    "rows": {
                        r: [
                            {
                                "id": u.instance_id,
                                "card_id": u.card.id,
                                "name": u.card.name,
                                "base": u.card.base_strength,
                                "current": u.current_strength,
                                "hero": u.card.hero,
                                "weathered": u.weathered,
                                "image": u.card.image_url(),
                                "row": r,
                                "type": u.card.type.value,
                                "tags": list(u.card.tags),
                            }
                            for u in self.board.units_in_row(p.discord_id, r)
                        ]
                        for r in ("melee", "ranged", "siege")
                    },
                    # Only reveal full hand to the viewer themselves
                    "hand": (
                        [
                            {
                                "id": ci.instance_id,
                                "card_id": ci.card.id,
                                "name": ci.card.name,
                                "type": ci.card.type.value,
                                "base": ci.card.base_strength,
                                "row": ci.card.row.value if ci.card.row else None,
                                "hero": ci.card.hero,
                                "image": ci.card.image_url(),
                                "description": ci.card.description,
                                "effects": [e.model_dump() for e in ci.card.effects],
                            }
                            for ci in p.hand
                        ]
                        if viewer_discord_id is not None and p.discord_id == viewer_discord_id
                        else None
                    ),
                }
                for p in self.players
            ],
            "weather": dict(self.board.weather),
            "log_tail": self.log[-15:],
        }
