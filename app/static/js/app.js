/* =========================================================================
   Gwent-like game client — WebSocket + state rendering
   ========================================================================= */

(function () {
  "use strict";

  // ----------------------------------------------------------- state
  let ws = null;
  let snapshot = null;
  let youId = null;
  let matchId = null;
  let token = null;
  let isYourTurn = false;
  let selectedCardInstanceId = null;

  // ----------------------------------------------------------- dom refs
  const $ = (id) => document.getElementById(id);
  const overlay = $("overlay");
  const overlayText = $("overlay-text");

  // ----------------------------------------------------------- entry
  window.addEventListener("DOMContentLoaded", () => {
    // Parse URL: /play/{match_id}?token=xxx
    const pathParts = window.location.pathname.split("/");
    matchId = pathParts[pathParts.length - 1] || pathParts[pathParts.length - 2];
    token = new URLSearchParams(window.location.search).get("token");
    if (!matchId || !token) {
      showOverlay("Неверная ссылка. Используйте кнопку из Discord-сообщения.", true);
      return;
    }
    connectWebSocket();
  });

  // ----------------------------------------------------------- WebSocket
  function connectWebSocket() {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${proto}//${window.location.host}/ws/${matchId}?token=${token}`;
    console.log("Connecting to", wsUrl);
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log("WS connected");
      hideOverlay();
    };

    ws.onmessage = (evt) => {
      let msg;
      try {
        msg = JSON.parse(evt.data);
      } catch (e) {
        console.error("Bad JSON", e);
        return;
      }
      handleMessage(msg);
    };

    ws.onerror = (err) => {
      console.error("WS error", err);
      showOverlay("Ошибка соединения. Переподключение…", false);
    };

    ws.onclose = () => {
      console.log("WS closed");
      if (snapshot && snapshot.phase !== "finished") {
        showOverlay("Соединение потеряно. Переподключение через 2 секунды…", false);
        setTimeout(connectWebSocket, 2000);
      }
    };
  }

  function send(msg) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg));
    }
  }

  function handleMessage(msg) {
    if (msg.type === "state") {
      snapshot = msg.snapshot;
      if (msg.you !== undefined) youId = msg.you;
      render();
    } else if (msg.type === "error") {
      showToast(msg.message);
    } else if (msg.type === "pong") {
      // ignore
    }
  }

  // ----------------------------------------------------------- render
  function render() {
    if (!snapshot) return;
    $("match-id").textContent = snapshot.match_id;
    $("round-current").textContent = snapshot.round;
    $("round-total").textContent = snapshot.rounds_total;
    $("phase").textContent = phaseLabel(snapshot.phase);

    isYourTurn = snapshot.current_player_id === youId && snapshot.phase === "in_progress";

    // Determine "you" vs "opponent(s)"
    const you = snapshot.players.find((p) => p.discord_id === youId);
    const opponents = snapshot.players.filter((p) => p.discord_id !== youId);

    // Top bar
    renderWeather(snapshot.weather);

    // Your area
    if (you) {
      renderPlayerArea(you, "you");
      renderHand(you);
    }

    // Opponent area (first opponent only for simplicity; if 3+ players, others fold into opponent area)
    if (opponents.length > 0) {
      renderPlayerArea(opponents[0], "opponent");
    }

    // Action buttons
    $("btn-leader").disabled = !isYourTurn || (you && you.leader_used_this_round);
    $("btn-pass").disabled = !isYourTurn;
    if (you) {
      $("your-leader-badge").textContent = you.leader_name
        ? `👑 ${you.leader_name}${you.leader_used_this_round ? " (использован)" : ""}`
        : "";
      $("your-leader-badge").className = "leader-badge" + (you.leader_used_this_round ? " used" : "");
    }
    if (opponents[0]) {
      $("opponent-leader-badge").textContent = opponents[0].leader_name
        ? `👑 ${opponents[0].leader_name}${opponents[0].leader_used_this_round ? " (исп.)" : ""}`
        : "";
      $("opponent-leader-badge").className = "leader-badge" + (opponents[0].leader_used_this_round ? " used" : "");
      $("opponent-passed").textContent = opponents[0].passed ? "пас" : "";
    }

    // Log
    renderLog(snapshot.log_tail || []);

    // If match finished, show overlay
    if (snapshot.phase === "finished") {
      const winner = snapshot.players.find((p) => p.discord_id === (snapshot.winner_id || -1));
      showOverlay(
        winner
          ? `🏆 Победитель: ${winner.name}!`
          : "🤝 Ничья!",
        false
      );
    }
  }

  function phaseLabel(phase) {
    return {
      created: "создание",
      in_progress: "идёт раунд",
      round_end: "конец раунда",
      finished: "завершён",
    }[phase] || phase;
  }

  function renderWeather(weather) {
    const strip = $("weather-strip");
    strip.innerHTML = "";
    const active = Object.entries(weather).filter(([_, v]) => v);
    if (active.length === 0) {
      const el = document.createElement("span");
      el.className = "weather-clear";
      el.textContent = "☀️ Ясно";
      strip.appendChild(el);
    } else {
      for (const [row, _] of active) {
        const el = document.createElement("span");
        el.className = "weather-badge";
        const icons = { melee: "❄️ Мороз", ranged: "🌫️ Туман", siege: "🌧️ Дождь" };
        el.textContent = icons[row] || row;
        strip.appendChild(el);
      }
    }
  }

  function renderPlayerArea(player, prefix) {
    $(prefix + "-name").textContent = player.name + (player.passed ? " 💤" : "");
    $(prefix + "-strength").textContent = player.total_strength;
    $(prefix + "-rounds").textContent = player.rounds_won;
    $(prefix + "-deck-size").textContent = player.deck_size;
    $(prefix + "-hand-size").textContent = player.hand_size;

    // Highlight current player
    const area = $(prefix === "you" ? "you-area" : "opponent-area");
    if (player.discord_id === snapshot.current_player_id && snapshot.phase === "in_progress") {
      area.classList.add("active-turn");
    } else {
      area.classList.remove("active-turn");
    }

    // Rows
    for (const rowName of ["melee", "ranged", "siege"]) {
      const rowEl = area.querySelector(`.row[data-row="${rowName}"]`);
      if (!rowEl) continue;
      const units = player.rows[rowName] || [];
      const unitsEl = rowEl.querySelector(".row-units");
      const strengthEl = rowEl.querySelector(".row-strength");
      unitsEl.innerHTML = "";
      strengthEl.textContent = units.reduce((s, u) => s + u.current, 0);

      // Weathered?
      if (snapshot.weather[rowName]) {
        rowEl.classList.add("weathered");
      } else {
        rowEl.classList.remove("weathered");
      }

      for (const unit of units) {
        const cardEl = renderCard(unit, { inHand: false });
        unitsEl.appendChild(cardEl);
      }
    }
  }

  function renderCard(unit, opts) {
    const card = document.createElement("div");
    card.className = "card";
    if (unit.hero) card.classList.add("hero");
    if (unit.weathered) card.classList.add("weathered");
    if (opts && opts.inHand) {
      card.classList.add("card-in-hand");
      if (isYourTurn) {
        card.classList.add("playable");
      } else {
        card.classList.add("disabled");
      }
      card.dataset.instanceId = unit.id;
    }
    if (unit.type === "unit" || unit.current !== undefined) {
      card.classList.add("strength-badge");
      card.dataset.strength = unit.current;
    }
    const img = document.createElement("img");
    img.src = unit.image;
    img.alt = unit.name;
    img.loading = "lazy";
    card.appendChild(img);

    // Hover tooltip
    card.addEventListener("mouseenter", (e) => showTooltip(unit, e));
    card.addEventListener("mouseleave", hideTooltip);

    // Click in hand -> play
    if (opts && opts.inHand) {
      card.addEventListener("click", () => onHandCardClick(unit));
    }
    return card;
  }

  function renderHand(player) {
    const handEl = $("your-hand");
    handEl.innerHTML = "";
    if (!player.hand) {
      handEl.innerHTML = '<div class="hand-placeholder">Рука скрыта</div>';
      return;
    }
    if (player.hand.length === 0) {
      handEl.innerHTML = '<div class="hand-placeholder">Рука пуста — используйте Пас</div>';
      return;
    }
    for (const card of player.hand) {
      const cardEl = renderCard(card, { inHand: true });
      handEl.appendChild(cardEl);
    }
  }

  function renderLog(lines) {
    const list = $("log-list");
    list.innerHTML = "";
    for (const line of lines.slice(-10).reverse()) {
      const li = document.createElement("li");
      li.textContent = line;
      list.appendChild(li);
    }
  }

  // ----------------------------------------------------------- card click
  function onHandCardClick(card) {
    if (!isYourTurn) {
      showToast("Сейчас не ваш ход.");
      return;
    }
    // Agile cards need a row choice
    if (card.row === "agile") {
      selectedCardInstanceId = card.id;
      showRowPicker((row) => {
        sendAction("play_card", { instance_id: card.id, target_row: row });
        selectedCardInstanceId = null;
      });
      return;
    }
    sendAction("play_card", { instance_id: card.id });
  }

  function showRowPicker(callback) {
    const picker = document.createElement("div");
    picker.className = "row-picker";
    picker.innerHTML = `
      <div class="row-picker-content">
        <h3>Выберите ряд для карты</h3>
        <div class="row-picker-buttons">
          <button class="row-picker-btn" data-row="melee">⚔️ Ближний бой</button>
          <button class="row-picker-btn" data-row="ranged">🏹 Дальний бой</button>
          <button class="row-picker-btn" data-row="cancel">Отмена</button>
        </div>
      </div>
    `;
    document.body.appendChild(picker);
    picker.querySelectorAll("button").forEach((btn) => {
      btn.addEventListener("click", () => {
        const row = btn.dataset.row;
        picker.remove();
        if (row !== "cancel") callback(row);
      });
    });
  }

  // ----------------------------------------------------------- actions
  function sendAction(action, params = {}) {
    send({ type: "action", action, ...params });
  }

  // Wire up action buttons
  document.addEventListener("DOMContentLoaded", () => {
    $("btn-leader").addEventListener("click", () => {
      if (confirm("Использовать способность лидера? Действие нельзя отменить.")) {
        sendAction("use_leader");
      }
    });
    $("btn-pass").addEventListener("click", () => {
      sendAction("pass");
    });
    $("btn-surrender").addEventListener("click", () => {
      if (confirm("Сдаться? Это закончит матч.")) {
        sendAction("surrender");
      }
    });
  });

  // ----------------------------------------------------------- tooltip
  function showTooltip(card, event) {
    const tip = $("card-tooltip");
    tip.innerHTML = "";
    if (card.image) {
      const img = document.createElement("img");
      img.src = card.image;
      tip.appendChild(img);
    }
    const h = document.createElement("h4");
    h.textContent = card.name;
    tip.appendChild(h);
    if (card.description) {
      const d = document.createElement("div");
      d.className = "desc";
      d.textContent = card.description;
      tip.appendChild(d);
    }
    if (card.effects && card.effects.length) {
      const eff = document.createElement("div");
      eff.className = "desc";
      eff.style.marginTop = "6px";
      eff.innerHTML = "<strong>Эффекты:</strong> " + card.effects.map((e) => e.type).join(", ");
      tip.appendChild(eff);
    }
    tip.classList.remove("hidden");
    // Position near cursor, but stay in viewport
    const x = Math.min(event.clientX + 16, window.innerWidth - 340);
    const y = Math.min(event.clientY + 16, window.innerHeight - 320);
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  }

  function hideTooltip() {
    $("card-tooltip").classList.add("hidden");
  }

  // ----------------------------------------------------------- helpers
  function showOverlay(text, isError) {
    overlayText.textContent = text;
    overlay.classList.remove("hidden");
    if (isError) {
      overlay.querySelector(".spinner").style.display = "none";
    } else {
      overlay.querySelector(".spinner").style.display = "block";
    }
  }

  function hideOverlay() {
    overlay.classList.add("hidden");
  }

  function showToast(message) {
    const toast = document.createElement("div");
    toast.className = "toast";
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
  }

  // Heartbeat to keep WS alive
  setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      send({ type: "ping" });
    }
  }, 30000);
})();
