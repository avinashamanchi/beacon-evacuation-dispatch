// BEACON dashboard logic — polls /api/state every 2s. Vanilla JS only.
// NOTE: map.js owns STREETS/PERIMETERS/PIN_COLOR/FLAGGED/renderPins/setPerimeter.
// Top-level names here must not collide with map.js (shared global scope).

let LAST = null;
let CASE_MAP = {};

const EQUIP_ICON = {
  oxygen: "O₂", dialysis: "DIA", refrigerated_meds: "MEDS",
  wheelchair_power: "PWR-CHAIR", other: "+", none: "", unknown: "",
};
const LANE_IDS = ["fire_rescue", "transport_assist", "accessible_shelter"];
const PATH_TITLE = {
  fire_rescue: "FIRE / RESCUE", transport_assist: "TRANSPORT",
  accessible_shelter: "SHELTER", needs_human_review: "HUMAN REVIEW",
  auto_answered: "AUTO-ANSWERED", standard: "STANDARD",
};

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// ---------- lane cards ----------
function caseCard(c) {
  const f = c.facts || {};
  const eq = c.equation;
  const equip = EQUIP_ICON[f.medical_equipment] || "";
  const review = c.dispatch_path === "needs_human_review"
    ? `<span class="badge">HUMAN REVIEW</span>` : "";
  const ack = c.status === "acknowledged" ? `<span class="st ack">EN ROUTE</span>` : "";
  const cf = (c.tone_rank && c.need_rank)
    ? `<span class="cf">tone #${c.tone_rank} → <b>beacon #${c.need_rank}</b></span>` : "<span></span>";
  return `<div id="card-${c.id}" class="case" onclick="openReceipt('${c.id}')" tabindex="0"
      onkeydown="if(event.key==='Enter')openReceipt('${c.id}')">
    <div class="who"><span>${esc(c.requester_name)}</span>${review}${ack}</div>
    <div class="loc">${equip ? equip + " · " : ""}${esc(f.location_text || "location unknown")}</div>
    ${eq ? `<div class="eq ${eq.time_to_impact < 0 ? "neg" : ""}">${eq.fire_eta} − ${eq.evac_need} = ${eq.time_to_impact} min</div>` : ""}
    <div class="meta">${cf}<span class="age${eq && eq.time_to_impact < 0 ? " overdue" : ""}"
      data-created="${esc(c.created_at)}"></span></div>
  </div>`;
}

function feedRow(c) {
  const tag = c.status === "resolved" ? `<span class="tag">RESOLVED</span>`
    : c.dispatch_path === "auto_answered" ? `<span class="tag">AUTO</span>` : "";
  return `<div id="card-${c.id}" class="row" onclick="openReceipt('${c.id}')">
    <span class="msg">${esc(c.requester_name)} — ${esc((c.message || "").slice(0, 60))}</span>${tag}
  </div>`;
}

// ---------- signature scatter: TONE (y) vs NEED (x) ----------
function needX(c) {
  // Map time-to-impact +60..-60 min onto 0..1 (right = more critical).
  const eq = c.equation;
  const tti = eq ? eq.time_to_impact : 60; // informational => far left
  return Math.min(1, Math.max(0, (60 - tti) / 120));
}

function drawScatter(cases) {
  const W = 560, H = 190, L = 34, R = 12, T = 16, B = 26;
  const iw = W - L - R, ih = H - T - B;
  const px = (v) => L + v * iw;
  const py = (v) => T + (1 - v / 100) * ih;
  const dots = cases.filter((c) => c.panic_score != null).map((c) => {
    const color = PIN_COLOR[c.dispatch_path] || "#70634E";
    const flagged = FLAGGED.has(c.dispatch_path);
    return `<circle cx="${px(needX(c)).toFixed(1)}" cy="${py(c.panic_score).toFixed(1)}"
      r="${flagged ? 5.5 : 3}" fill="${color}" fill-opacity="${flagged ? .95 : .5}"
      stroke="#14100C" stroke-width="1" style="cursor:pointer"
      onmouseover="highlightCard('${c.id}', true)" onmouseout="highlightCard('${c.id}', false)"
      onclick="openReceipt('${c.id}')"><title>${esc(c.requester_name)} — tone ${c.panic_score}</title></circle>`;
  }).join("");

  document.getElementById("scatter").innerHTML = `
    <line x1="${L}" y1="${T}" x2="${L}" y2="${H - B}" stroke="#3B3122"/>
    <line x1="${L}" y1="${H - B}" x2="${W - R}" y2="${H - B}" stroke="#3B3122"/>
    <line x1="${px(.5)}" y1="${T}" x2="${px(.5)}" y2="${H - B}" stroke="#2B2419" stroke-dasharray="3 4"/>
    <line x1="${L}" y1="${py(50)}" x2="${W - R}" y2="${py(50)}" stroke="#2B2419" stroke-dasharray="3 4"/>
    <text x="${L - 6}" y="${T + 8}" fill="#70634E" font-size="9" text-anchor="end"
      font-family="'IBM Plex Mono',monospace" transform="rotate(-90 ${L - 6} ${T + 8})">HOW LOUD →</text>
    <text x="${W - R}" y="${H - 8}" fill="#70634E" font-size="9" text-anchor="end"
      font-family="'IBM Plex Mono',monospace">HOW URGENT →</text>
    <text x="${px(.03)}" y="${py(93)}" fill="#70634E" font-size="10"
      font-family="'Barlow Condensed',sans-serif" letter-spacing="2">LOUD &amp; FINE</text>
    <text x="${px(.62)}" y="${py(6)}" fill="#FF8C5A" font-size="10"
      font-family="'Barlow Condensed',sans-serif" letter-spacing="2">CALM &amp; CRITICAL</text>
    ${dots}`;
}

// ---------- render ----------
function render(data) {
  const prevFlagged = LAST && LAST.metrics ? LAST.metrics.flagged : null;
  LAST = data;
  CASE_MAP = {};
  data.cases.forEach((c) => (CASE_MAP[c.id] = c));
  if (prevFlagged != null && data.metrics && data.metrics.flagged > prevFlagged) pingDispatch();

  const m = data.metrics || {};
  document.getElementById("fireEta").textContent = data.fire.eta_minutes + "m";
  document.getElementById("mTotal").textContent = m.total ?? 0;
  document.getElementById("mDeflect").innerHTML = `${m.deflected_pct ?? 0}<span class="unit">%</span>`;
  document.getElementById("mFlagged").textContent = m.flagged ?? 0;
  document.getElementById("mMs").innerHTML = `${m.median_ms ?? 0}<span class="unit">ms</span>`;
  setPerimeter(data.fire.perimeter_step);

  const mode = data.mode || {};
  document.getElementById("modeLine").textContent =
    (mode.demo ? "DEMO" : "LIVE") + " · " +
    (mode.mock_zendesk ? "mock zendesk" : "zendesk connected") + " · " +
    (mode.fallback_extraction ? "keyword extraction" : "openai extraction");

  const replayBtn = document.getElementById("replayBtn");
  replayBtn.textContent = data.sim_running ? "Replaying…" : "Replay incident";
  replayBtn.disabled = !!data.sim_running;

  // Lanes + load bars.
  const byLane = { fire_rescue: [], transport_assist: [], accessible_shelter: [] };
  const noise = [];
  data.cases.forEach((c) => {
    if (c.status === "resolved") noise.push(c);
    else if (c.dispatch_path === "needs_human_review") byLane.fire_rescue.push(c);
    else if (byLane[c.dispatch_path]) byLane[c.dispatch_path].push(c);
    else noise.push(c);
  });
  for (const lane of LANE_IDS) {
    document.getElementById("cards-" + lane).innerHTML =
      byLane[lane].map(caseCard).join("") || `<div class="empty">no active cases</div>`;
    const info = (m.lanes || {})[lane] || { active: 0, capacity: 0, saturated: false };
    document.getElementById("cap-" + lane).textContent =
      `${info.active}/${info.capacity}${info.saturated ? " SAT" : ""}`;
    const bar = document.getElementById("bar-" + lane);
    bar.classList.toggle("sat", info.saturated);
    bar.firstElementChild.style.width =
      Math.min(100, info.capacity ? (100 * info.active / info.capacity) : 0) + "%";
  }
  document.getElementById("cards-noise").innerHTML = noise.map(feedRow).join("");
  const counts = data.counts || {};
  document.getElementById("feedCount").textContent =
    `${counts.standard || 0} standard · ${counts.auto_answered || 0} auto`;

  renderPins(data.cases);
  drawScatter(data.cases);

  // Pager.
  const escs = data.escalations || [];
  document.getElementById("pager").innerHTML = escs.length
    ? escs.map((e) => `<div class="row">📟 <b>${esc(e.team)}</b> · ${esc(e.case_id)} · ${esc(e.location)}${
        e.status === "internal_note_fallback" ? " (note)" : ""}</div>`).join("")
    : `<div class="row">standing by</div>`;

  // Radio log: newest timeline event across all cases.
  let latest = null;
  data.cases.forEach((c) => (c.timeline || []).forEach((t) => {
    if (!latest || t.at > latest.at) latest = { ...t, who: c.requester_name };
  }));
  if (latest) {
    document.getElementById("radio").textContent =
      `${latest.at.slice(11, 19)}Z  ${latest.who} — ${latest.event}`;
  }
}

function highlightCard(id, on) {
  const el = document.getElementById("card-" + id);
  if (el) {
    el.classList.toggle("hl", on);
    if (on) el.scrollIntoView({ block: "nearest" });
  }
}

// ---------- receipt ----------
function openReceipt(id) {
  const c = CASE_MAP[id];
  if (!c) return;
  const f = c.facts || {};
  const eq = c.equation;
  const escn = c.escalation;
  const factRows = Object.entries(f).map(([k, v]) =>
    `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("");
  const timeline = (c.timeline || []).map((t) =>
    `<li><span class="t">${esc((t.at || "").slice(11, 19))}</span><span>${esc(t.event)}</span></li>`).join("");

  document.getElementById("modalBody").innerHTML = `
    <div class="stamp">AUDITED</div>
    <h2>Dispatch receipt</h2>
    <div class="sub">BEACON · case ${esc(c.id)} · ${esc((c.created_at || "").slice(0, 19))}Z</div>
    <hr>
    <div class="msgq">"${esc(c.message)}"</div>
    <hr>
    <div class="sec">EXTRACTED FACTS — MODEL OUTPUT, NEVER A DECISION</div>
    <table>${factRows}</table>
    <div class="sec">RULE FIRED — DETERMINISTIC, 25 LINES, AUDITABLE</div>
    <div class="rule-line">${esc(c.rule_fired)}</div>
    ${eq ? `<div class="sec">EQUATION</div>
      <div class="eqbig ${eq.time_to_impact < 0 ? "neg" : ""}">fire ETA ${eq.fire_eta} − evac need ${eq.evac_need} = ${eq.time_to_impact} min</div>` : ""}
    <div class="sec">COUNTERFACTUAL</div>
    <div>tone score ${c.panic_score ?? "—"}/100 · a tone-ranked queue serves this <b>#${c.tone_rank ?? "—"}</b>;
      BEACON serves it <b>#${c.need_rank ?? "—"}</b></div>
    ${c.auto_answer ? `<div class="sec">AUTO-ANSWER (FROM GUIDE)</div><div>${esc(c.auto_answer)}</div>` : ""}
    <div class="sec">ESCALATION</div>
    <div>${escn ? `${esc(escn.team)} via ${esc(escn.channel)} — ${esc(escn.status)}` : "none"}</div>
    <div class="sec">TIMELINE</div>
    <ul>${timeline}</ul>
    <hr>
    <div>zendesk ticket ${c.zendesk_ticket_id ? "#" + esc(c.zendesk_ticket_id) : "—"} · pipeline ${esc(c.processing_ms ?? "—")}ms</div>
    ${c.status !== "open" ? `<div class="status-line ${esc(c.status)}">status: ${esc(c.status)}</div>` : ""}
    ${c.status !== "resolved" && FLAGGED.has(c.dispatch_path) ? `<div class="actions">
      ${c.status === "open" ? `<button onclick="doCaseAction('${c.id}','acknowledge')">Acknowledge</button>` : ""}
      <button onclick="doCaseAction('${c.id}','resolve')">Resolve</button>
      <select id="reassign-${c.id}">
        <option value="">Override to…</option>
        <option value="fire_rescue">fire_rescue</option>
        <option value="transport_assist">transport_assist</option>
        <option value="accessible_shelter">accessible_shelter</option>
        <option value="standard">standard</option>
      </select>
      <button onclick="doReassign('${c.id}')">Apply</button>
    </div>` : ""}
    <div class="actions">
      ${c.zendesk_ticket_id ? `<button onclick="showZendesk(${JSON.stringify(c.zendesk_ticket_id)}, '${c.id}')">View in Zendesk</button>` : ""}
      <button onclick="downloadReceipt('${c.id}')">Download JSON</button>
      <button onclick="closeModal()">Close</button>
    </div>`;
  document.getElementById("modal").classList.remove("hidden");
}

async function doCaseAction(id, action, path) {
  try {
    const res = await fetch("/api/case/" + id, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(path ? { action, path } : { action }),
    });
    if (!res.ok) return;
    const updated = await res.json();
    CASE_MAP[id] = updated;
    openReceipt(id);      // refresh the receipt with new status/timeline
    poll();
  } catch (err) { /* leave receipt as-is */ }
}

function doReassign(id) {
  const sel = document.getElementById("reassign-" + id);
  if (sel && sel.value) doCaseAction(id, "reassign", sel.value);
}

function downloadReceipt(id) {
  const c = CASE_MAP[id];
  if (!c) return;
  const blob = new Blob([JSON.stringify(c, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `beacon-receipt-${c.id}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
}

function closeModal() { document.getElementById("modal").classList.add("hidden"); }
document.getElementById("modal").addEventListener("click", (e) => {
  if (e.target.id === "modal") closeModal();
});

// ---------- dispatch ping (Web Audio, no assets) ----------
let audioCtx = null;
let soundOn = localStorage.getItem("beacon-sound") === "on";

function updateSoundBtn() {
  const b = document.getElementById("soundBtn");
  if (b) b.textContent = soundOn ? "🔔" : "🔕";
}
function toggleSound() {
  soundOn = !soundOn;
  localStorage.setItem("beacon-sound", soundOn ? "on" : "off");
  if (soundOn) {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    audioCtx.resume();
    pingDispatch(true);
  }
  updateSoundBtn();
}
function pingDispatch(force) {
  if ((!soundOn && !force) || !audioCtx) return;
  const t = audioCtx.currentTime;
  [[880, 0], [660, 0.13]].forEach(([freq, dt]) => {
    const o = audioCtx.createOscillator();
    const g = audioCtx.createGain();
    o.frequency.value = freq; o.type = "sine";
    g.gain.setValueAtTime(0.001, t + dt);
    g.gain.exponentialRampToValueAtTime(0.12, t + dt + 0.01);
    g.gain.exponentialRampToValueAtTime(0.001, t + dt + 0.12);
    o.connect(g).connect(audioCtx.destination);
    o.start(t + dt); o.stop(t + dt + 0.14);
  });
}

// ---------- zendesk proof view ----------
async function showZendesk(ticketId, caseId) {
  try {
    const res = await fetch("/api/zendesk/tickets");
    const data = await res.json();
    if (data.live) { window.open(data.agent_url, "_blank"); return; }
    const t = (data.tickets || []).find((x) => x.id === ticketId);
    if (!t) return;
    const comments = (t.comments || []).map((cm) => cm.public
      ? `<div class="zd-public"><b>Public reply:</b> ${esc(cm.body)}</div>`
      : `<div class="zd-note">${esc(cm.body)}</div>`).join("");
    document.getElementById("modalBody").innerHTML = `
      <h2>Zendesk ticket #${esc(t.id)}</h2>
      <div class="sub">write-back proof · demo-mode mirror of the live Support API calls</div>
      <div class="zd">
        <div class="zd-h">${esc(t.subject)}</div>
        <div class="zd-b">
          <div class="zd-row"><span class="k">Requester</span><span>${esc(t.requester)}</span></div>
          <div class="zd-row"><span class="k">Priority</span><span>${esc(t.priority)}</span></div>
          <div class="zd-row"><span class="k">dispatch_path</span><span><b>${esc(t.custom_field ?? "—")}</b></span></div>
          <div class="zd-row"><span class="k">Tags</span><span>${(t.tags || []).map((x) => `<span class="zd-tag">${esc(x)}</span>`).join("")}</span></div>
          ${comments}
        </div>
      </div>
      <div class="actions">
        <button onclick="openReceipt('${esc(caseId)}')">← Back to receipt</button>
        <button onclick="closeModal()">Close</button>
      </div>`;
  } catch (err) { /* keep modal as-is */ }
}

// ---------- help ----------
function toggleHelp() { document.getElementById("help").classList.toggle("hidden"); }

// ---------- controls + shortcuts ----------
async function seedDemo(n) { await fetch("/api/seed/demo/" + n, { method: "POST" }); poll(); }
async function advanceFire() { await fetch("/api/fire/advance", { method: "POST" }); poll(); }
async function startReplay() { await fetch("/api/simulate", { method: "POST" }); poll(); }
async function resetIncident() { await fetch("/api/reset", { method: "POST" }); LAST = null; poll(); }

document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
  if (e.key === "Escape") {
    document.getElementById("help").classList.add("hidden");
    return closeModal();
  }
  if (e.key === "?") return toggleHelp();
  if (!document.getElementById("modal").classList.contains("hidden")) return;
  const k = e.key.toLowerCase();
  if (["1", "2", "3", "4"].includes(k)) seedDemo(+k);
  else if (k === "f") advanceFire();
  else if (k === "r") startReplay();
  else if (k === "m") toggleSound();
});
updateSoundBtn();

// ---------- clock + polling ----------
function tickClock() {
  document.getElementById("clock").textContent = new Date().toTimeString().slice(0, 8);
  // Live case aging — ticks every second between polls.
  document.querySelectorAll(".age[data-created]").forEach((el) => {
    const secs = Math.max(0, Math.floor((Date.now() - Date.parse(el.dataset.created)) / 1000));
    el.textContent = `${String(Math.floor(secs / 60)).padStart(2, "0")}:${String(secs % 60).padStart(2, "0")}`;
  });
}
async function poll() {
  try {
    const res = await fetch("/api/state");
    if (res.ok) render(await res.json());
  } catch (err) { /* keep last render; never blank */ }
}
setInterval(tickClock, 1000);
setInterval(poll, 2000);
tickClock();
poll();
