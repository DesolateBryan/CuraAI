/*
 * CuraAI bridge for the MockChart demo page (ADR-005: "the demo page posts the FHIR
 * bundle and patient messages to the FastAPI backend over local HTTP").
 *
 * Loaded only when the backend serves the page at /mockchart (same origin, no CORS).
 * It is a humble view: no clinical logic lives here.
 *   1. Every patient message (existing unread ones, and every new one) is POSTed to
 *      /api/messages together with that patient's FHIR R4 bundle.
 *   2. Follow-up questions waiting in /api/outbox are posted into the patient's thread
 *      with MockEpic.send(), which makes MockChart's simulated patient reply.
 *   3. When a review is ready, a "CuraAI" panel offers to open it.
 *   4. On every page load it asks the server what it already has for each patient, so a
 *      reload never shows an empty panel. MockChart's "Reset test data" button, and the
 *      panel's "Re-run" button, send the messages again. If the server can't be reached,
 *      the panel says so and keeps retrying.
 * Only the backend decides anything. This script loops, posts and displays.
 */
(() => {
  "use strict";
  if (!window.MockEpic) { console.warn("[CuraAI] window.MockEpic not found; bridge inactive"); return; }

  const api = window.MockEpic.connect(window.MockEpic.devKey);
  const SENT_KEY = "curaai.bridge.sent.v1";
  const INSTANCE_KEY = "curaai.bridge.instance.v1";
  const POLL_MS = 1500;
  const RETRY_MS = 3000;
  const status = {};                         // patient_id -> {outcome, review_url}
  let server = "connecting";                 // "connecting" | "ok" | "down"

  const sent = (() => { try { return new Set(JSON.parse(localStorage.getItem(SENT_KEY)) || []); } catch (e) { return new Set(); } })();
  const remember = id => { sent.add(id); try { localStorage.setItem(SENT_KEY, JSON.stringify([...sent])); } catch (e) {} };
  const forgetSent = () => { sent.clear(); try { localStorage.setItem(SENT_KEY, "[]"); } catch (e) {} };

  // MockChart's seed messages have no timezone; they are page-local times.
  const toIso = t => (/[zZ]|[+-]\d\d:\d\d$/.test(t) ? t : new Date(t).toISOString());
  const messageId = (pid, m) => `${pid}-${toIso(m.t).replace(/[^0-9]/g, "").slice(0, 14)}`;

  async function postMessage(pid, m) {
    const id = messageId(pid, m);
    if (sent.has(id)) return;
    remember(id);
    setStatus(pid, { outcome: "sending" });
    try {
      const res = await fetch("/api/messages", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message_id: id, patient_id: pid, sent_at: toIso(m.t), text: m.text,
                               origin: "patient", fhir_bundle: api.fhir(pid) }),
      });
      const body = await res.json();
      setStatus(pid, res.ok ? body : { outcome: "error", error: body.error || res.status });
    } catch (e) {
      sent.delete(id);                       // not delivered: allow a retry
      setStatus(pid, { outcome: "error", error: "Can't reach the CuraAI server" });
    }
  }

  async function pollOutbox() {
    try {
      const res = await fetch("/api/outbox");
      if (res.ok) {
        for (const f of (await res.json()).follow_ups) {
          setStatus(f.patient_id, { outcome: "follow_up_sent" });
          api.send(f.patient_id, f.display_text);  // "Automated question from CuraAI: <catalog text>", as the backend sent it
        }
      }
    } catch (e) { /* backend restarting; try again next tick */ }
    setTimeout(pollOutbox, POLL_MS);
  }

  // ---- panel (display only) -------------------------------------------------------------
  const LABELS = { sending: "Screening…", follow_up_sent: "Waiting for the patient's answer",
                   packet_delivered: "Review ready", handed_off_incomplete: "Handed off (incomplete)", error: "Error" };
  const panel = document.createElement("div");
  panel.id = "curaai-panel";
  panel.style.cssText = "position:fixed;right:14px;bottom:14px;z-index:9999;width:300px;max-height:60vh;overflow:auto;" +
    "background:#fff;color:#1b2430;border:1px solid #d9e0e8;border-top:3px solid #e8890c;box-shadow:0 6px 24px #0003;" +
    "font:13px/1.4 'Segoe UI',system-ui,sans-serif";
  document.body.appendChild(panel);

  const overlay = document.createElement("div");
  overlay.style.cssText = "position:fixed;inset:0;z-index:10000;background:#0008;display:none";
  overlay.innerHTML = '<div style="position:absolute;inset:4vh 4vw;background:#fff;display:flex;flex-direction:column">' +
    '<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 10px;background:#143a5e;color:#fff">' +
    '<b>CuraAI review</b><button id="curaai-close" style="font:inherit">Close</button></div>' +
    '<iframe id="curaai-frame" title="CuraAI review" style="flex:1;border:0;width:100%"></iframe></div>';
  document.body.appendChild(overlay);
  overlay.querySelector("#curaai-close").onclick = () => { overlay.style.display = "none"; };

  function setStatus(pid, s) { status[pid] = s; render(); }

  function render() {
    const rows = Object.entries(status).map(([pid, s]) => {
      const link = s.review_url ? `<button data-review="${s.review_url}" style="font:inherit;margin-top:4px">Open review</button>` : "";
      const err = s.error ? `<div style="color:#b3261e">${String(s.error).replace(/</g, "&lt;")}</div>` : "";
      return `<div style="padding:8px 10px;border-top:1px solid #d9e0e8"><b>${pid}</b> · ${LABELS[s.outcome] || s.outcome}${err}${link}</div>`;
    }).join("");
    const header = '<div style="display:flex;justify-content:space-between;align-items:center;padding:7px 10px">' +
      '<b style="color:#1a6bb5">CuraAI</b><button id="curaai-rerun" title="Send every patient message to CuraAI again" ' +
      'style="font:inherit;font-size:12px">Re-run</button></div>';
    const notice = server === "down"
      ? '<div style="padding:8px 10px;color:#b3261e">Can\'t reach the CuraAI server. Check that ' +
        '<code>python -m curaai.app.main</code> is running, then this panel reconnects by itself.</div>'
      : server === "connecting" ? '<div style="padding:8px 10px;color:#5d6b7c">Connecting to CuraAI…</div>'
      : (rows ? "" : '<div style="padding:8px 10px;color:#5d6b7c">No patient messages to screen. ' +
                     'Click Re-run to send them again.</div>');
    panel.innerHTML = header + notice + rows;
    panel.querySelector("#curaai-rerun").onclick = () => rerun();
    panel.querySelectorAll("[data-review]").forEach(b => b.onclick = () => {
      overlay.querySelector("#curaai-frame").src = b.dataset.review; overlay.style.display = "block";
    });
  }

  // ---- start ---------------------------------------------------------------------------------
  async function serverInstance() {
    try {
      const res = await fetch("/api/health");
      if (!res.ok) throw new Error(String(res.status));
      server = "ok";
      return (await res.json()).instance;
    } catch (e) {
      server = "down"; render();
      return null;
    }
  }

  // Ask the server what it already has, so a reload shows the real state instead of an empty panel.
  async function restoreStatus() {
    for (const p of api.patients()) {
      try {
        const res = await fetch(`/api/patients/${encodeURIComponent(p.id)}/review`);
        if (res.ok) {
          const b = await res.json();
          status[p.id] = { outcome: b.outcome, review_url: b.review_url };
        }
      } catch (e) { /* shown as missing; sendAll will retry */ }
    }
    render();
  }

  async function sendAll() {
    for (const p of api.patients()) {
      for (const m of api.messages(p.id).filter(m => m.from === "p")) await postMessage(p.id, m);
    }
  }

  async function rerun() {
    forgetSent();
    for (const k of Object.keys(status)) delete status[k];
    render();
    await sendAll();
  }

  async function start() {
    const instance = await serverInstance();
    if (instance === null) { setTimeout(start, RETRY_MS); return; }
    // The server keeps cases in memory, so after a restart it has forgotten every message.
    // If the server instance changed, forget what this page already sent and send it again.
    try {
      if (localStorage.getItem(INSTANCE_KEY) !== instance) {
        forgetSent();
        localStorage.setItem(INSTANCE_KEY, instance);
      }
    } catch (e) { /* storage blocked: carry on */ }
    await restoreStatus();
    await sendAll();
  }

  // MockChart's "Reset test data" puts the original messages back, so screen them again.
  document.addEventListener("click", e => {
    if (e.target && e.target.id === "reset") setTimeout(rerun, 300);
  }, true);

  render();
  api.onPatientMessage((pid, m) => postMessage(pid, m));
  start();
  pollOutbox();
  window.CuraAIBridge = { status, postMessage, rerun };   // for tests and debugging
})();
