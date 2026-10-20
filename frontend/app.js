/* Rubik's Cube Race - frontend. Talks only to our backend (/api/*); the OpenRouter key
   never reaches the browser. */
(() => {
  "use strict";

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const api = async (path, opts) => {
    const r = await fetch(path, opts);
    if (!r.ok) {
      let msg = r.statusText;
      try {
        const body = await r.json();
        // FastAPI: {"detail": "text"} or {"detail": [{"msg": ..., "loc": [...]}]}
        msg = typeof body.detail === "string" ? body.detail
          : Array.isArray(body.detail) ? body.detail.map((d) => `${d.loc?.slice(-1)[0] ?? ""}: ${d.msg}`).join("; ")
          : JSON.stringify(body);
      } catch { /* non-JSON body */ }
      const err = new Error(msg);
      err.status = r.status;
      throw err;
    }
    return r.json();
  };
  const isActive = (run) => !!run && (run.status === "running" || run.status === "pending");

  const FACES = "URFDLB";
  const STATUS = {
    solved: { text: "SOLVED ✓", ribbon: "Solved", cls: "good" },
    move_limit: { text: "NOT SOLVED", ribbon: "Ran out of moves", cls: "bad" },
    out_of_time: { text: "NOT SOLVED", ribbon: "Out of time", cls: "bad" },
    invalid_limit: { text: "NOT SOLVED", ribbon: "Too many invalid outputs", cls: "bad" },
    api_error: { text: "API ERROR", ribbon: "API error", cls: "bad" },
    cancelled: { text: "STOPPED", ribbon: "Stopped", cls: "bad" },
    interrupted: { text: "INTERRUPTED", ribbon: "Interrupted", cls: "bad" },
    budget_exhausted: { text: "NOT SOLVED", ribbon: "API budget reached", cls: "bad" },
  };
  const ORD = (n) => (n === 1 ? "st" : n === 2 ? "nd" : n === 3 ? "rd" : "th");

  const S = {
    config: null,
    run: null,
    fetchedAt: 0,
    viewIdx: null,       // puzzle index pinned by the user; null = follow live
    pollGen: 0,          // bumps whenever we start following a different run
    lastStates: {},
    lastMoveCounts: {},
    slideShownFor: null,
  };

  // ------------------------------------------------------------------ helpers
  function fmtClock(sec) {
    if (sec == null) return "–";
    const m = Math.floor(sec / 60);
    const s = sec - m * 60;
    return `${m}:${s.toFixed(2).padStart(5, "0")}`;
  }
  function fmtSecs(sec) {
    if (sec == null) return "–";
    return sec < 60 ? `${sec.toFixed(2)} s` : `${fmtClock(sec)} min`;
  }
  function fmtMs(ms) {
    if (ms == null) return "–";
    return ms >= 1000 ? `${(ms / 1000).toFixed(2)} s` : `${Math.round(ms)} ms`;
  }
  const fmtNum = (v, d = 2) => (v == null ? "–" : Number(v).toFixed(d));
  const model = (key) => S.config.models.find((m) => m.key === key);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // ------------------------------------------------------------------ 3D cube
  function makeCube(stage) {
    const cube = document.createElement("div");
    cube.className = "cube3d";
    for (const f of FACES) {
      const face = document.createElement("div");
      face.className = `face3d f-${f}`;
      for (let i = 0; i < 9; i++) face.appendChild(document.createElement("i"));
      cube.appendChild(face);
    }
    stage.appendChild(cube);
    // Drag to rotate (default view shows U, F and R).
    let rx = -26, ry = -38, drag = null;
    const apply = () => (cube.style.transform = `rotateX(${rx}deg) rotateY(${ry}deg)`);
    apply();
    stage.addEventListener("pointerdown", (e) => {
      drag = { x: e.clientX, y: e.clientY, rx, ry };
      stage.setPointerCapture(e.pointerId);
    });
    stage.addEventListener("pointermove", (e) => {
      if (!drag) return;
      ry = drag.ry + (e.clientX - drag.x) * 0.6;
      rx = Math.max(-89, Math.min(89, drag.rx - (e.clientY - drag.y) * 0.6));
      apply();
    });
    stage.addEventListener("pointerup", () => (drag = null));
    stage.addEventListener("dblclick", () => { rx = -26; ry = -38; apply(); });
    return cube;
  }

  function paintCube(cube, state) {
    const faces = $$(".face3d", cube);
    FACES.split("").forEach((f, k) => {
      const cells = faces[k].children;
      for (let i = 0; i < 9; i++) cells[i].className = `k-${state[k * 9 + i]}`;
    });
  }

  // ------------------------------------------------------------------ cards
  function buildCards() {
    const grid = $("#race-grid");
    grid.innerHTML = "";
    for (const m of S.config.models) {
      const card = document.createElement("article");
      card.className = "card";
      card.id = `card-${m.key}`;
      card.innerHTML = `
        <div class="card-head">
          <span class="swatch" style="background:${m.color}"></span>
          <span class="card-name">${esc(m.name)}</span>
          <span class="badge ${m.category}">${m.category === "llm" ? "Frontier LLM" : "Decision model"}</span>
          <span class="card-id">${esc(m.model_id)}</span>
        </div>
        <div class="card-body">
          <div class="cube-stage" title="Drag to rotate · double-click to reset">
            <div class="medal hidden"></div>
            <div class="ribbon hidden"></div>
          </div>
          <div class="stats">
            <div class="stat"><div class="stat-k">Time</div><div class="stat-v" data-f="time">0:00.00</div></div>
            <div class="stat"><div class="stat-k">Moves</div><div class="stat-v" data-f="moves">0</div></div>
            <div class="stat"><div class="stat-k">Latency / move</div><div class="stat-v" data-f="lat">–</div></div>
            <div class="stat"><div class="stat-k">API calls · cache</div><div class="stat-v" data-f="inv">0 · 0</div></div>
            <div class="stat wide">
              <div><div class="stat-k">Current move</div><div class="cur-move" data-f="cur">–</div></div>
              <div class="status-line" data-f="status">waiting</div>
            </div>
          </div>
        </div>
        <div class="history" data-f="hist"></div>
        <div class="card-foot"><span data-f="foot"></span><span data-f="conf"></span></div>
        <div class="err" data-f="err"></div>`;
      grid.appendChild(card);
      card._cube = makeCube($(".cube-stage", card));
      paintCube(card._cube, S.config.solved);
    }
  }

  function currentPuzzle() {
    if (!S.run) return null;
    const idx = S.viewIdx ?? S.run.current;
    return S.run.puzzles[idx] || null;
  }

  function trialElapsed(t) {
    if (!t) return 0;
    // While the backend is unreachable the clock freezes instead of running on.
    if (t.status === "running" && isActive(S.run)) return t.elapsed_s + (S.connLost ? 0 : (performance.now() - S.fetchedAt) / 1000);
    return t.total_time_s ?? t.elapsed_s ?? 0;
  }

  function renderCards() {
    const p = currentPuzzle();
    for (const m of S.config.models) {
      const card = $(`#card-${m.key}`);
      const t = p && p.trials[m.key];
      card.style.opacity = t || !p ? "1" : ".35";
      const f = (k) => $(`[data-f="${k}"]`, card);
      const state = t ? t.state : p ? p.state : S.config.solved;
      const sk = `${p ? p.index : "-"}:${m.key}`;
      if (S.lastStates[sk] !== state) {
        paintCube(card._cube, state);
        if (S.lastStates[sk] !== undefined) {
          const stage = card._cube.parentElement;
          stage.classList.remove("pulse");
          void stage.offsetWidth;
          stage.classList.add("pulse");
        }
        S.lastStates[sk] = state;
      }
      const medal = $(".medal", card), ribbon = $(".ribbon", card);
      card.classList.remove("solved", "winner");
      if (!t) {
        medal.classList.add("hidden"); ribbon.classList.add("hidden");
        f("time").textContent = "0:00.00"; f("moves").textContent = "0"; f("lat").textContent = "–";
        f("inv").textContent = "0 · 0"; f("cur").textContent = "–"; f("hist").innerHTML = "";
        $(".card-name", card).textContent = m.name; $(".card-id", card).textContent = m.model_id;
        f("status").className = "status-line"; f("status").textContent = p ? "not in this run" : "waiting";
        f("foot").textContent = ""; f("conf").textContent = ""; f("err").textContent = "";
        continue;
      }
      f("time").textContent = fmtClock(trialElapsed(t));
      f("moves").innerHTML = `${t.move_count}<small> / ${S.run.settings.max_moves}</small>`;
      f("lat").textContent = fmtMs(t.avg_latency_ms);
      f("inv").textContent = `${t.api_calls ?? 0} · ${t.cache_hits ?? 0}`;
      // Show the model that actually played this slot (Ollama runs use local stand-ins).
      const mid = S.run.settings.model_ids?.[m.key] || m.model_id;
      $(".card-name", card).textContent = S.run.mode === "ollama" ? mid : m.name;
      $(".card-id", card).textContent = S.run.mode === "ollama" ? `${m.name} slot` : mid;
      const last = t.moves[t.moves.length - 1];
      f("cur").textContent = last ? last.move : "–";
      const st = f("status");
      const fin = STATUS[t.status];
      if (t.status === "running" && isActive(S.run)) {
        st.className = "status-line thinking";
        st.innerHTML = `<span class="dots">${t.phase || "deciding"}</span>`;
      } else if (fin) {
        st.className = `status-line ${fin.cls}`;
        st.textContent = fin.text;
      } else {
        st.className = "status-line"; st.textContent = "waiting";
      }
      if (fin && p.status === "done") {
        ribbon.className = `ribbon ${fin.cls}`; ribbon.textContent = fin.ribbon;
        if (t.rank) {
          medal.className = `medal r${Math.min(t.rank, 4)}`;
          medal.innerHTML = `${t.rank}<sup>${ORD(t.rank).toUpperCase()}</sup>`;
        }
        if (t.status === "solved") card.classList.add("solved");
        if (t.rank === 1 && t.status === "solved") card.classList.add("winner");
      } else if (fin) {
        ribbon.className = `ribbon ${fin.cls}`; ribbon.textContent = fin.ribbon; medal.className = "medal hidden";
      } else {
        ribbon.className = "ribbon hidden"; medal.className = "medal hidden";
      }
      // Move history (re-render only when it grows).
      const hk = `${sk}:${t.move_count}:${t.invalid.length}`;
      if (S.lastMoveCounts[sk] !== hk) {
        const items = [];
        const invalidAt = (n) => t.invalid.filter((iv) => iv.after_move === n)
          .map((iv) => `<span class="mv bad" title="${esc(iv.error)}: ${esc(iv.raw)}">✗ invalid</span>`);
        items.push(...invalidAt(0));
        t.moves.forEach((mv, i) => {
          items.push(`<span class="mv${i === t.moves.length - 1 ? " last" : ""}${mv.source === "cache" ? " src-cache" : ""}" title="#${mv.n} · ${fmtMs(mv.latency_ms)}${mv.source === "cache" ? " (from cache)" : ""}${mv.confidence != null ? ` · conf ${mv.confidence}` : ""}">${esc(mv.move)}</span>`);
          items.push(...invalidAt(mv.n));
        });
        const h = f("hist");
        h.innerHTML = items.join("");
        h.scrollTop = h.scrollHeight;
        S.lastMoveCounts[sk] = hk;
      }
      const opt = p.optimal_moves;
      let foot = opt != null ? `Optimal: ${opt} moves` : "Optimal: unknown (> 8)";
      if (t.status === "solved" && opt != null) foot += ` · gap +${t.move_count - opt}`;
      if (t.status !== "running" && t.final_distance != null && t.status !== "solved") foot += ` · ended ${t.final_distance} from solved`;
      f("foot").textContent = foot;
      const extra = `invalid ${t.invalid.length} · retries ${t.retries}` + (t.cost_usd ? ` · $${t.cost_usd.toFixed(4)}` : "");
      f("conf").textContent = (last && last.confidence != null ? `confidence ${(last.confidence * 100).toFixed(0)}% · ` : "") + extra;
      f("err").textContent = t.error ? `⚠ ${t.error}` : "";
    }
  }

  function renderPuzzleBar() {
    const run = S.run;
    if (!run) return;
    const p = currentPuzzle();
    const label = S.config.test_sets[run.test_set]?.label || run.test_set;
    $("#pb-title").textContent = `${label} · Puzzle ${p.index + 1} of ${run.puzzles.length}` +
      (isActive(run) ? "" : run.status === "done" ? " · run complete" : run.status === "cancelled" ? " · run stopped" : ` · ${run.status}`);
    $("#pb-meta").innerHTML =
      `Scramble <code>${esc(p.scramble.join(" "))}</code> · shortest solution ` +
      (p.optimal_moves != null ? `<b>${p.optimal_moves}</b> moves <code>${esc(p.optimal_solution.join(" "))}</code>` : "<b>unknown</b> (beyond exact BFS range)") +
      ` · limit ${run.settings.max_moves} moves · run <span class="mono">${run.id}</span> · ${run.mode.toUpperCase()}`;
    const chips = run.puzzles.map((q) => {
      const cls = [q.index === p.index ? "cur" : "", q.status === "done" ? "done" : "", q.status === "running" ? "running" : ""].join(" ");
      const winner = q.status === "done" ? Object.values(q.trials).find((t) => t.rank === 1 && t.status === "solved") : null;
      const dot = winner ? ` <span style="color:${model(winner.model).color}">●</span>` : "";
      return `<button class="chip ${cls}" data-i="${q.index}">P${q.index + 1}${dot}</button>`;
    });
    if (S.viewIdx != null) chips.push(`<button class="chip" data-i="live">⟲ follow live</button>`);
    $("#pb-chips").innerHTML = chips.join("");
  }

  function renderBanner() {
    const run = S.run, el = $("#result-banner");
    const p = currentPuzzle();
    const actions = isActive(run) ? "" : `<button class="btn ghost" data-go="dash">View dashboard</button><button class="btn primary" data-go="slide">Benchmark slide →</button>`;
    if (run && p && (p.status === "cancelled" || p.status === "interrupted")) {
      const what = p.status === "cancelled" ? "stopped" : "interrupted (server stopped)";
      el.innerHTML = `<h3>Puzzle ${p.index + 1} ${what}</h3><div class="muted" style="flex:1;min-width:240px">Unfinished puzzles are not ranked and are left out of the statistics.</div>${actions}`;
      el.classList.remove("hidden");
      return;
    }
    if (!run || !p || p.status !== "done") { el.classList.add("hidden"); return; }
    const trials = Object.values(p.trials).sort((a, b) => a.rank - b.rank);
    const parts = trials.map((t) => {
      const m = model(t.model);
      const st = t.status === "solved" ? `solved in ${t.move_count} moves` : (STATUS[t.status]?.ribbon || t.status).toLowerCase();
      return `<span>${t.rank}. <b style="color:${m.color}">${esc(m.name)}</b> — ${st}, ${fmtSecs(t.total_time_s)}</span>`;
    });
    const live = isActive(run);
    const title = !live ? (run.status === "cancelled" ? "Run stopped" : run.status === "done" ? "Benchmark complete" : `Run ${run.status}`)
      : `Puzzle ${p.index + 1} finished`;
    const next = live && run.next_puzzle_at && S.viewIdx == null
      ? `<span class="next-in" data-next="${run.next_puzzle_at}"></span>` : "";
    el.innerHTML = `<h3>${title}${next}</h3>
      <div style="display:flex;flex-direction:column;gap:2px;flex:1;min-width:240px">${parts.join("")}</div>
      ${actions}`;
    el.classList.remove("hidden");
  }

  function renderRace() {
    if (!S.config) return;
    renderCards();
    if (S.run) { renderPuzzleBar(); renderBanner(); }
    const running = isActive(S.run);
    $("#btn-run").disabled = running;
    $("#btn-cancel").disabled = !running;
    renderModePill();
  }

  function renderModePill() {
    const mode = S.run ? S.run.mode : (S.config.mode === "mock" ? "mock" : "live");
    let label = { mock: "MOCK MODE · simulated", ollama: "OLLAMA · local models", live: "LIVE · OpenRouter" }[mode] || mode;
    if (S.run?.settings?.replay_from_cache) label = "LIVE RUN · replayed from cache";
    const pill = $("#mode-pill");
    pill.textContent = label;
    pill.className = `mode-pill ${mode}`;
  }

  async function refreshBudget() {
    try {
      const b = await api("/api/budget");
      const claudeId = S.config.models.find((m) => m.category === "llm").model_id;
      const c = b.per_model[claudeId] || 0;
      const el = $("#budget-pill");
      el.innerHTML = `API calls <b>${b.total}/${b.limits.total}</b> · Claude <b>${c}/${b.limits.claude}</b>` +
        (b.cost_usd ? ` · $${b.cost_usd.toFixed(4)}` : "");
      el.classList.toggle("full", b.total >= b.limits.total);
      el.classList.toggle("hidden", S.config.mode === "mock");
    } catch { /* ignore */ }
  }

  // Smooth timers between polls.
  function tick() {
    const p = currentPuzzle();
    if (p) {
      for (const [k, t] of Object.entries(p.trials)) {
        if (t.status === "running" && isActive(S.run)) {
          const el = $(`#card-${k} [data-f="time"]`);
          if (el) el.textContent = fmtClock(trialElapsed(t));
        }
      }
    }
    const nx = $(".next-in");
    if (nx) {
      // Server and browser run on the same machine here, so the clocks agree.
      const left = Math.max(0, Math.ceil(Number(nx.dataset.next) - Date.now() / 1000));
      nx.textContent = ` · next puzzle in ${left}s`;
    }
    requestAnimationFrame(tick);
  }

  // ------------------------------------------------------------------ polling
  async function loadRun(id) {
    const run = await api(`/api/runs/${id}`);
    S.pollGen++;                       // stop following whatever we followed before
    S.run = run;
    S.fetchedAt = performance.now();
    S.lastStates = {}; S.lastMoveCounts = {};
    $("#ctl-runs").value = id;
    renderRace();
    if (isActive(S.run)) startPolling();
  }

  function setConnLost(lost) {
    if (lost && !S.connLost) {
      // Freeze the clocks at the last known value.
      const p = currentPuzzle();
      if (p) for (const t of Object.values(p.trials)) if (t.status === "running") t.elapsed_s = trialElapsed(t);
    }
    S.connLost = lost;
    $("#conn-warning").classList.toggle("hidden", !lost);
  }

  // The server no longer has this run (it was restarted before the run was saved):
  // show it as interrupted locally and stop following it.
  function markGone(run) {
    run.status = "interrupted";
    for (const p of run.puzzles) {
      if (p.status === "running" || p.status === "pending") p.status = "interrupted";
      for (const t of Object.values(p.trials)) if (t.status === "running" || t.status === "pending") { t.status = "interrupted"; t.phase = ""; }
    }
  }

  async function startPolling() {
    const gen = ++S.pollGen;
    const id = S.run.id;
    let wasLive = false;
    while (gen === S.pollGen && isActive(S.run)) {
      wasLive = true;
      await new Promise((r) => setTimeout(r, 200));
      if (gen !== S.pollGen) return;
      try {
        const run = await api(`/api/runs/${id}`);
        if (gen !== S.pollGen) return;
        S.run = run;
        S.fetchedAt = performance.now();
        setConnLost(false);
        renderRace();
        if (run.mode === "live" && (S.budgetTick = (S.budgetTick || 0) + 1) % 5 === 0) refreshBudget();
      } catch (e) {
        if (e.status === 404) {
          setConnLost(false);
          markGone(S.run);
          break;
        }
        setConnLost(true);
        await new Promise((r) => setTimeout(r, 1000));
      }
    }
    if (gen !== S.pollGen) return;
    renderRace();
    refreshBudget();
    refreshRunList().catch(() => {});
    // Auto-open the slide only for a run we watched finish normally.
    if (wasLive && S.run.id === id && S.run.status === "done" && $("#ctl-autoslide").checked && S.slideShownFor !== id) {
      S.slideShownFor = id;
      setTimeout(() => { if (S.run && S.run.id === id) showView("slide"); }, 2500);
    }
  }

  async function refreshRunList() {
    const runs = await api("/api/runs");
    const sel = $("#ctl-runs");
    const cur = S.run?.id || "";
    sel.innerHTML = `<option value="">—</option>` + runs.map((r) =>
      `<option value="${r.id}">${r.id} · ${r.test_set} · ${r.puzzles}p · ${r.mode}${r.status === "running" ? " · running" : ""}</option>`).join("");
    sel.value = cur;
    return runs;
  }

  // ------------------------------------------------------------------ dashboard
  async function fetchStats() {
    const scope = $("#dash-scope").value;
    const mode = $("#dash-mode").value;
    const q = new URLSearchParams();
    if (scope === "run" && S.run) q.set("run_id", S.run.id);
    if (mode) q.set("mode", mode);
    return api(`/api/stats?${q}`);
  }

  function pickSet(stats, preferred) {
    const sets = Object.keys(stats.sets);
    if (preferred && stats.sets[preferred]) return preferred;
    for (const s of [S.run?.test_set, "primary", "warmup", "extension", "all"]) if (s && stats.sets[s]) return s;
    return sets[0];
  }

  function barChart(title, note, rows, field, fmt, lowerBetter) {
    const vals = rows.map((r) => r[field]).filter((v) => v != null);
    const max = Math.max(...vals, 0) || 1;
    const best = vals.length ? (lowerBetter ? Math.min(...vals) : Math.max(...vals)) : null;
    const items = rows.map((r) => {
      const v = r[field];
      const w = v == null ? 0 : Math.max(0.5, (v / max) * 100);
      const m = model(r.model);
      return `<div class="bar-row" data-tip="${esc(m.name)}: ${esc(fmt(v))}${v === best ? (lowerBetter ? " (lowest)" : " (highest)") : ""}">
        <span class="bar-label">${esc(m.name)}</span>
        <span class="bar-track"><span class="bar" style="width:${w}%;background:${m.color}"></span></span>
        <span class="bar-val">${esc(fmt(v))}</span></div>`;
    }).join("");
    return `<div class="chart"><h4>${title}</h4><div class="note">${note}</div>${items}</div>`;
  }

  function answerTexts(block) {
    const rows = block.models;
    const a = block.answers || {};
    const by = (k) => rows.find((r) => r.model === k);
    const nm = (k) => (k ? model(k).name : "–");
    // "A", "A & B", "A, B & C"
    const list = (keys) => { const n = (keys || []).map(nm); return n.length > 1 ? `${n.slice(0, -1).join(", ")} & ${n[n.length - 1]}` : (n[0] || "–"); };
    // Headline form: "A" or "Tie: A & B".
    const names = (keys) => (keys && keys.length > 1 ? `Tie: ${list(keys)}` : list(keys));
    // In a sentence: "A had" / "A & B shared".
    const who = (keys) => `${list(keys)} ${keys && keys.length > 1 ? "shared" : "had"}`;
    const fastest = by(a.fastest);
    const rateTied = a.highest_solve_rate_tied || (a.highest_solve_rate ? [a.highest_solve_rate] : []);
    const gapTied = a.shortest_solutions_tied || (a.shortest_solutions ? [a.shortest_solutions] : []);
    const best = by(rateTied[0]), shortest = by(gapTied[0]);
    const llm = rows.find((r) => r.category === "llm");
    // Best decision model: solve rate, then optimal gap, then latency.
    const bestDec = rows.filter((r) => r.category === "decision").sort((x, y) =>
      (y.success_rate - x.success_rate) || ((x.avg_optimal_gap ?? 1e9) - (y.avg_optimal_gap ?? 1e9)) ||
      ((x.avg_latency_ms ?? 1e9) - (y.avg_latency_ms ?? 1e9)))[0];
    let q5 = "Not enough data.";
    if (llm && bestDec && !rows.some((r) => r.solved > 0)) {
      const byDone = rows.slice().sort((x, y) => (y.avg_cube_completion_pct ?? 0) - (x.avg_cube_completion_pct ?? 0));
      q5 = `No model solved this cube within its limits, so neither style is good enough on its own here. Closest: ${list(byDone.filter((r) => r.avg_cube_completion_pct === byDone[0].avg_cube_completion_pct).map((r) => r.model))} (${fmtNum(byDone[0].avg_cube_completion_pct, 0)}% of stickers placed). A hybrid with a search-based planner would be needed.`;
    } else if (llm && bestDec) {
      const llmGap = llm.avg_optimal_gap, decGap = bestDec.avg_optimal_gap;
      if (llm.success_rate > bestDec.success_rate || (llm.success_rate === bestDec.success_rate && llmGap != null && decGap != null && llmGap < decGap)) {
        q5 = `Hybrid. ${llm.name} solved ${llm.success_rate.toFixed(0)}% (gap ${llmGap != null ? "+" + fmtNum(llmGap) : "–"}) vs ${bestDec.success_rate.toFixed(0)}% (gap ${decGap != null ? "+" + fmtNum(decGap) : "–"}) for ${bestDec.name}, but each move took ${fmtMs(llm.avg_latency_ms)} vs ${fmtMs(bestDec.avg_latency_ms)}. Use the fast model for routine steps and escalate to the LLM (or a solver) when progress stalls.`;
      } else {
        q5 = `Decision model. ${bestDec.name} matched or beat ${llm.name} (${bestDec.success_rate.toFixed(0)}% vs ${llm.success_rate.toFixed(0)}% solved, gap ${decGap != null ? "+" + fmtNum(decGap) : "–"} vs ${llmGap != null ? "+" + fmtNum(llmGap) : "–"}) at ${fmtMs(bestDec.avg_latency_ms)} per move instead of ${fmtMs(llm.avg_latency_ms)}.`;
      }
    }
    let q4 = "–";
    if (!best) q4 = `${nm(a.fastest)} was fastest, but no model solved a puzzle, so quality is compared by cube completion only.`;
    else if (a.fastest) {
      q4 = a.fastest_is_best_quality
        ? `<strong>Yes</strong> — ${nm(a.fastest)} was fastest and also ${rateTied.length > 1 || gapTied.length > 1 ? "shared" : "had"} the best solve rate and optimal gap.`
        : `<strong>No</strong> — ${nm(a.fastest)} was fastest, but ${
          gapTied.length && list(rateTied) === list(gapTied)
            ? `${who(rateTied)} both the best solve rate and the shortest solutions`
            : `${who(rateTied)} the best solve rate${gapTied.length ? ` and ${who(gapTied)} the shortest solutions` : ""}`}.`;
    }
    return [
      ["1 · Fastest decisions", fastest ? `<strong>${nm(a.fastest)}</strong> at ${fmtMs(fastest.avg_latency_ms)} per move.` : "–"],
      ["2 · Highest solve rate", best ? `<strong>${names(rateTied)}</strong> with ${best.success_rate.toFixed(0)}% (${best.solved}/${best.trials}).` : "No model solved any puzzle in this set."],
      ["3 · Shortest solutions", shortest ? `<strong>${names(gapTied)}</strong>, average gap +${fmtNum(shortest.avg_optimal_gap)} moves over the BFS optimum${gapTied.length === 1 ? ` (${shortest.optimal_solves}/${shortest.gap_samples} exactly optimal)` : ""}.` : "No solved puzzle with a known optimum."],
      ["4 · Fastest = best quality?", q4],
      ["5 · What would I use?", q5],
    ];
  }

  let dashToken = 0, slideToken = 0;
  async function renderDash() {
    const body = $("#dash-body");
    const token = ++dashToken;
    let stats;
    try { stats = await fetchStats(); } catch (e) { body.innerHTML = `<div class="panel empty">${esc(e.message)}</div>`; return; }
    if (token !== dashToken) return;
    const sets = Object.keys(stats.sets);
    const setSel = $("#dash-set");
    const prev = setSel.value;
    setSel.innerHTML = sets.map((s) => `<option value="${s}">${esc(stats.sets[s].label)}</option>`).join("");
    const chosen = pickSet(stats, prev);
    setSel.value = chosen || "";
    $("#dash-info").textContent = `${stats.runs} run(s) included`;
    if (!chosen) {
      body.innerHTML = `<div class="panel empty">No finished puzzles yet. Run a benchmark from the Race tab.</div>`;
      return;
    }
    const block = stats.sets[chosen];
    const rows = block.models;
    const bestOf = (field, lower) => {
      const v = rows.map((r) => r[field]).filter((x) => x != null);
      return v.length && new Set(v).size > 1 ? (lower ? Math.min(...v) : Math.max(...v)) : null;
    };
    const cols = [
      ["Trials", "trials"], ["Solved", "solved"],
      ["Success rate", "success_rate", (v) => `${v.toFixed(0)}%`, false],
      ["Avg latency / move", "avg_latency_ms", fmtMs, true],
      ["Median latency", "median_latency_ms", fmtMs],
      ["Avg total time", "avg_total_time_s", fmtSecs],
      ["Total moves", "total_moves"],
      ["Avg moves (solved)", "avg_moves_solved", (v) => fmtNum(v), true],
      ["Avg optimal", "avg_optimal_moves", (v) => fmtNum(v)],
      ["Optimal gap", "avg_optimal_gap", (v) => `+${fmtNum(v)}`, true],
      ["Gap = 0", null],
      ["Cube completion", "avg_cube_completion_pct", (v) => `${fmtNum(v, 1)}%`, false],
      ["Invalid", "invalid_outputs"], ["Retries", "retries"],
      ["API calls", "live_api_calls"], ["Cache hits", "cache_hits"],
      ["Live latency", "avg_live_latency_ms", fmtMs],
      ["Cache served", "avg_cache_served_ms", (v) => `${v.toFixed(2)} ms`],
      ["Cost", "cost_usd", (v) => `$${v.toFixed(4)}`],
    ];
    const head = `<tr><th>Model</th>${cols.map((c) => `<th>${c[0]}</th>`).join("")}</tr>`;
    const trs = rows.map((r) => {
      const m = model(r.model);
      const tds = cols.map(([, field, fmt, lower]) => {
        if (field === null) return `<td>${r.optimal_solves}/${r.gap_samples}</td>`;
        const v = r[field];
        const hl = lower !== undefined && v != null && v === bestOf(field, lower);
        return `<td style="${hl ? "color:var(--good)" : ""}">${v == null ? "–" : fmt ? fmt(v) : v}${hl ? " ★" : ""}</td>`;
      }).join("");
      return `<tr><td><span class="swatch" style="display:inline-block;background:${m.color};margin-right:8px;vertical-align:-1px"></span>${esc(m.name)}</td>${tds}</tr>`;
    }).join("");
    const charts = [
      barChart("Avg latency per move", "Mean wall time of one model call · lower is faster", rows, "avg_latency_ms", fmtMs, true),
      barChart("Success rate", "Puzzles solved within the move limit", rows, "success_rate", (v) => (v == null ? "–" : `${v.toFixed(0)}%`), false),
      barChart("Avg optimal gap (solved)", "Model moves − exact BFS shortest · 0 = optimal", rows, "avg_optimal_gap", (v) => (v == null ? "–" : `+${v.toFixed(2)}`), true),
      barChart("Avg total time per puzzle", "Start to solved / limit / timeout", rows, "avg_total_time_s", fmtSecs, true),
      barChart("Total moves", "All moves executed across trials", rows, "total_moves", (v) => (v == null ? "–" : String(v)), true),
      barChart("Cube completion at end", "Stickers matching their centre (100% = solved)", rows, "avg_cube_completion_pct", (v) => (v == null ? "–" : `${v.toFixed(1)}%`), false),
    ].join("");
    const answers = answerTexts(block).map(([q, a]) => `<div class="answer"><b>${q}</b>${a}</div>`).join("");
    body.innerHTML = `
      <div class="panel dash-section">
        <h2>${esc(block.label)}</h2>
        <div class="sub">${block.puzzles} puzzle(s) · ${rows.reduce((s, r) => s + r.trials, 0)} model-puzzle trials · ★ = best value</div>
        <div class="table-wrap"><table class="stats-table">${head}${trs}</table></div>
        <div class="charts">${charts}</div>
      </div>
      <div class="panel dash-section"><h2>Answers to the experiment questions</h2><div class="answers">${answers}</div></div>`;
  }

  // ------------------------------------------------------------------ slide
  async function renderSlide() {
    const el = $("#slide");
    const token = ++slideToken;
    let stats;
    try { stats = await fetchStats(); } catch (e) { el.innerHTML = esc(e.message); return; }
    if (token !== slideToken) return;
    // Selected-run scope: show that run's test set. All-runs scope: follow the dashboard's choice.
    const preferred = $("#dash-scope").value === "run" && S.run ? S.run.test_set : $("#dash-set").value;
    const setKey = pickSet(stats, preferred);
    const st = S.config.student;
    if (!setKey) {
      el.innerHTML = `<div class="s-top"><div><div class="s-kicker">Statistical benchmark</div><h2>No results yet</h2></div>
        <div class="s-student"><div>${esc(st.name)}</div><div>${esc(st.roll)}</div></div></div>`;
      return;
    }
    const block = stats.sets[setKey];
    const rows = block.models;
    const slideMode = $("#dash-scope").value === "run" && S.run ? S.run.mode : ($("#dash-mode").value || "");
    const metrics = [
      ["Success rate", "success_rate", (v) => `${v.toFixed(0)}%`, false],
      ["Avg latency / move", "avg_latency_ms", fmtMs, true],
      // Context only (no star): a model that crashes early would "win" these.
      ["Avg total time", "avg_total_time_s", fmtSecs],
      ["Total moves", "total_moves", (v) => String(v)],
      ["Avg moves (solved)", "avg_moves_solved", (v) => fmtNum(v, 1), true],
      ["Optimal gap", "avg_optimal_gap", (v) => `+${fmtNum(v)}`, true],
      ["Optimal solves", "optimal_solves", (v) => String(v), false],
      ["Cube completion", "avg_cube_completion_pct", (v) => `${fmtNum(v, 0)}%`, false],
      ["Invalid outputs", "invalid_outputs", (v) => String(v), true],
      ["API calls · cache", "live_api_calls", (v, r) => `${v} · ${r.cache_hits}`],
      ["Actual cost", "cost_usd", (v) => `$${v.toFixed(4)}`],
    ];
    const best = {};
    for (const [, f, , lower] of metrics) {
      if (lower === undefined) continue;  // informational rows get no star
      const v = rows.map((r) => r[f]).filter((x) => x != null);
      // No star when every model has the same value: nobody is "best".
      best[f] = v.length && new Set(v).size > 1 ? (lower ? Math.min(...v) : Math.max(...v)) : undefined;
    }
    const colsHtml = rows.map((r) => {
      const m = model(r.model);
      const ms = metrics.map(([k, f, fmt]) => {
        const v = r[f];
        const isBest = v != null && best[f] !== undefined && v === best[f] && rows.length > 1;
        return `<div class="s-metric${isBest ? " best" : ""}"><span>${k}</span><span>${v == null ? "–" : fmt(v, r)}</span></div>`;
      }).join("");
      return `<div class="s-col" style="border-top-color:${m.color}">
        <div><div class="s-name">${esc(slideName(m))}</div><div class="s-type">${slideType(m)}</div></div>
        ${ms}</div>`;
    }).join("");
    const ans = answerTexts(block).map(([q, a]) => `<div class="s-ans"><b>${q}</b>${a}</div>`).join("");
    function slideName(m) { return slideMode === "ollama" ? (S.run?.settings.model_ids?.[m.key] || m.ollama_model) : m.name; }
    function slideType(m) {
      if (slideMode === "ollama") return `Ollama · ${m.name} slot`;
      return m.category === "llm" ? "Frontier LLM · chat completions" : "Decision model · Decisions API";
    }
    const modes = S.run ? ({ live: "LIVE OPENROUTER", ollama: "OLLAMA", mock: "MOCK" }[S.run.mode] || S.run.mode.toUpperCase()) : "";
    el.innerHTML = `
      <div class="s-top">
        <div>
          <div class="s-kicker">Rubik's Cube Race · Statistical benchmark</div>
          <h2>${esc(block.label)} — speed vs. solution quality</h2>
          <div class="s-sub">${block.puzzles} puzzle${block.puzzles === 1 ? "" : "s"} × ${rows.length} models · max ${S.config.limits.max_moves} moves · exact optimum by BFS (HTM) · ${$("#dash-scope").value === "run" && S.run ? `run ${S.run.id} (${modes})` : `${stats.runs} runs`}</div>
        </div>
        <div class="s-student"><div>${esc(st.name)}</div><div>${esc(st.roll)}</div></div>
      </div>
      <div class="s-cols">${colsHtml}</div>
      <div class="s-answers">${ans}</div>
      <div class="s-foot"><span>★ best value per metric · Optimal gap = model moves − exact shortest moves (solved puzzles)</span><span>OpenRouter · Decisions API + Chat Completions</span></div>`;
  }

  // ------------------------------------------------------------------ views
  function showView(v) {
    if (history.replaceState) history.replaceState(null, "", v === "race" ? location.pathname : `#${v}`);
    $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === v));
    $$(".view").forEach((s) => s.classList.toggle("active", s.id === `view-${v}`));
    if (v === "dash") renderDash();
    if (v === "slide") renderSlide();
  }

  // ------------------------------------------------------------------ init
  async function init() {
    S.config = await api("/api/config");
    $("#student-name").textContent = S.config.student.name;
    $("#student-roll").textContent = S.config.student.roll;
    renderModePill();
    $("#ctl-provider").innerHTML = S.config.providers.map((p) =>
      `<option value="${p.key}" ${p.available ? "" : "disabled"}>${esc(p.label)}${p.available ? "" : ` — ${esc(p.reason)}`}</option>`).join("");
    $("#ctl-provider").value = "mock";
    $("#ctl-provider").addEventListener("change", (e) => {
      if (e.target.value === "live") {   // the budgeted live experiment: one 3-move puzzle
        $("#ctl-set").value = "live3";
        $("#ctl-count").value = 1;
      }
    });
    refreshBudget();
    $("#ctl-set").innerHTML = Object.entries(S.config.test_sets).map(([k, v]) =>
      `<option value="${k}">${v.label}${v.exact_optimal ? "" : ` (${v.min}–${v.max} turns)`}</option>`).join("");
    $("#ctl-set").value = "primary";
    $("#ctl-count").value = S.config.test_sets.primary.default_puzzles;
    $("#ctl-set").addEventListener("change", (e) => ($("#ctl-count").value = S.config.test_sets[e.target.value].default_puzzles));
    buildCards();

    $("#btn-run").addEventListener("click", async () => {
      const count = Number($("#ctl-count").value);
      if ($("#ctl-count").value.trim() === "" || !Number.isInteger(count) || count < 1 || count > 50) {
        alert("Puzzles must be a whole number from 1 to 50.");
        $("#ctl-count").focus();
        return;
      }
      $("#ctl-count").value = count;
      const seedRaw = $("#ctl-seed").value.trim();
      const seed = seedRaw === "" ? null : Number(seedRaw);
      if (seedRaw !== "" && !Number.isInteger(seed)) {
        alert("Seed must be a whole number, or empty for a random seed.");
        return;
      }
      const provider = $("#ctl-provider").value;
      const body = { test_set: $("#ctl-set").value, puzzles: count, seed, provider };
      if (provider === "live") {
        const b = await api("/api/budget");
        const ok = confirm(`This sends REAL OpenRouter requests (cached answers are reused first).\n\n` +
          `Budget used so far: ${b.total}/${b.limits.total} requests. Claude is capped at ${b.limits.claude}, ` +
          `each decision model at ${b.limits.per_decision_model}; the backend stops each model when its budget is used.\n\nStart the live run?`);
        if (!ok) return;
      }
      try {
        $("#btn-run").disabled = true;
        const run = await api("/api/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        S.pollGen++;
        S.run = run;
        S.fetchedAt = performance.now();
        S.viewIdx = null; S.lastStates = {}; S.lastMoveCounts = {};
        showView("race");
        renderRace();
        refreshRunList().catch(() => {});
        startPolling();
      } catch (e) {
        alert(`Could not start the run.\n\n${e.message}`);
        renderRace();
      }
    });
    $("#btn-cancel").addEventListener("click", () => {
      if (!S.run) return;
      $("#btn-cancel").disabled = true;
      api(`/api/runs/${S.run.id}/cancel`, { method: "POST" }).catch(() => {});
    });
    $("#ctl-runs").addEventListener("change", (e) => {
      if (e.target.value) { S.viewIdx = null; loadRun(e.target.value).catch((err) => alert(err.message)); }
    });
    $("#pb-chips").addEventListener("click", (e) => {
      const b = e.target.closest(".chip");
      if (!b) return;
      S.viewIdx = b.dataset.i === "live" ? null : Number(b.dataset.i);
      renderRace();
    });
    $("#result-banner").addEventListener("click", (e) => { const g = e.target.closest("[data-go]"); if (g) showView(g.dataset.go); });
    $$(".tab").forEach((t) => t.addEventListener("click", () => showView(t.dataset.view)));
    ["#dash-scope", "#dash-mode", "#dash-set"].forEach((s) => $(s).addEventListener("change", renderDash));
    $("#btn-refresh").addEventListener("click", renderDash);

    // Tooltips for chart bars.
    const tip = $("#tooltip");
    document.addEventListener("mousemove", (e) => {
      const row = e.target.closest("[data-tip]");
      if (!row) { tip.classList.add("hidden"); return; }
      tip.textContent = row.dataset.tip;
      tip.style.left = `${e.clientX + 14}px`;
      tip.style.top = `${e.clientY + 14}px`;
      tip.classList.remove("hidden");
    });

    const runs = await refreshRunList();
    const wanted = new URLSearchParams(location.search).get("run");
    const active = runs.find((r) => r.id === wanted) || runs.find((r) => r.status === "running") || runs[0];
    if (active) await loadRun(active.id);
    requestAnimationFrame(tick);
    const hv = location.hash.slice(1);
    if (["dash", "slide"].includes(hv)) showView(hv);
  }

  init().catch((e) => {
    document.body.insertAdjacentHTML("afterbegin", `<div style="padding:16px;background:#f2555a;color:#fff">Failed to load: ${esc(e.message)}</div>`);
  });
})();
