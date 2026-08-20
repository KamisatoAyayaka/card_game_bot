"""Player statistics service (wins, losses, ELO, leaderboard)."""
from __future__ import annotations

import math

from app.database import get_db
from app.models.card import PlayerStats


# ELO config — tuned for 2-4 player matches.
ELO_K = 32
ELO_BASE = 1000


class StatsService:
    @classmethod
    async def get_or_create(cls, discord_id: int, display_name: str | None = None) -> PlayerStats:
        db = await get_db()
        async with db.execute(
            "SELECT * FROM players WHERE discord_id=?", (discord_id,)
        ) as cur:
            row = await cur.fetchone()
        if row:
            return PlayerStats.from_db_row(row)
        await db.execute(
            "INSERT INTO players (discord_id, display_name) VALUES (?, ?)",
            (discord_id, display_name),
        )
        await db.commit()
        return PlayerStats(discord_id=discord_id, display_name=display_name, elo=ELO_BASE)

    @classmethod
    async def record_result(
        cls,
        winner_id: int | None,
        participant_ids: list[int],
        draw: bool = False,
    ) -> None:
        """Update wins/losses/draws + ELO for all participants.

        For matches with >2 players, ELO is computed as the average of pairwise
        deltas vs the winner (or vs the field average on a draw).
        """
        db = await get_db()
        stats_map: dict[int, PlayerStats] = {}
        for pid in participant_ids:
            stats_map[pid] = await cls.get_or_create(pid)

        if draw or winner_id is None:
            # All players get a draw, no ELO change vs avg (treat as 0.5 vs field avg)
            for pid, ps in stats_map.items():
                ps.draws += 1
                ps.matches_played += 1
                ps.last_played_at = "now"
            await cls._persist(stats_map)
            return

        winner = stats_map[winner_id]
        losers = [stats_map[pid] for pid in participant_ids if pid != winner_id]

        # Compute ELO deltas. Multiplayer: winner gets avg delta vs each loser,
        # each loser gets the negative of their pairwise delta vs the winner.
        winner_total_delta = 0.0
        loser_deltas: dict[int, float] = {pid: 0.0 for pid in participant_ids if pid != winner_id}
        for loser in losers:
            expected_w = 1.0 / (1.0 + 10.0 ** ((loser.elo - winner.elo) / 400.0))
            expected_l = 1.0 - expected_w
            delta_w = ELO_K * (1.0 - expected_w)
            delta_l = ELO_K * (0.0 - expected_l)
            winner_total_delta += delta_w
            loser_deltas[loser.discord_id] += delta_l

        if losers:
            winner_total_delta /= len(losers)

        winner.elo = max(0, round(winner.elo + winner_total_delta))
        winner.wins += 1
        winner.matches_played += 1
        winner.last_played_at = "now"

        for loser in losers:
            loser.elo = max(0, round(loser.elo + loser_deltas[loser.discord_id]))
            loser.losses += 1
            loser.matches_played += 1
            loser.last_played_at = "now"

        await cls._persist(stats_map)

    @classmethod
    async def _persist(cls, stats_map: dict[int, PlayerStats]) -> None:
        db = await get_db()
        for ps in stats_map.values():
            await db.execute(
                """
                UPDATE players
                SET display_name=?, wins=?, losses=?, draws=?, elo=?,
                    matches_played=?, last_played_at=datetime('now')
                WHERE discord_id=?
                """,
                (
                    ps.display_name,
                    ps.wins,
                    ps.losses,
                    ps.draws,
                    ps.elo,
                    ps.matches_played,
                    ps.discord_id,
                ),
            )
        await db.commit()

    @classmethod
    async def leaderboard(cls, limit: int = 10) -> list[PlayerStats]:
        db = await get_db()
        async with db.execute(
            "SELECT * FROM players ORDER BY elo DESC, wins DESC LIMIT ?",
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
        return [PlayerStats.from_db_row(r) for r in rows]
