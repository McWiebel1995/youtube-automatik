"use strict";
/* Cicco Zentrale – Cockpit. Eine Übersicht über alle Projekte, Konten, Freigaben und Aufträge.
   Aufträge (Freitext) landen als Ticket im privaten Repo cicco-zentrale und werden stündlich von Claude erledigt. */
const REPO = "McWiebel1995/youtube-automatik";
const API = `https://api.github.com/repos/${REPO}`;
const PAGES = "https://mcwiebel1995.github.io/youtube-automatik";
const inApp = () => !!(window.pywebview && window.pywebview.api);
const P = () => window.pywebview.api;
const bridge = {
  async catalog() { return inApp() ? P().catalog() : { depts: [], has_token: false, orders_repo: "" }; },
  async fetch(url) {
    if (inApp()) return P().fetch(url);
    try { const r = await fetch(url); return r.ok ? r.json() : { error: "HTTP " + r.status }; } catch (e) { return { error: String(e) }; }
  },
  async dispatch(id, ok) { return inApp() ? P().dispatch(id, ok) : { ok: false, msg: "Nur im Programm" }; },
  async clip(ids, action, edits) { return inApp() ? P().clip_decide(ids, action, edits || {}) : { ok: false, msg: "Nur im Programm" }; },
  async orders() { return inApp() ? P().orders() : { error: "Nur im Programm" }; },
  async orderCreate(t, b, p) { return inApp() ? P().order_create(t, b, p) : { ok: false, msg: "Nur im Programm" }; },
  async thread(n) { return inApp() ? P().order_thread(n) : { error: "Nur im Programm" }; },
  async reply(n, t) { return inApp() ? P().order_reply(n, t) : { ok: false, msg: "Nur im Programm" }; },
  async setToken(t) { return inApp() ? P().set_token(t) : { ok: false, msg: "Nur im Programm" }; },
  async clearToken() { return inApp() ? P().clear_token() : true; },
  open(u) { if (inApp()) P().open(u); else window.open(u, "_blank", "noopener"); },
};
const $ = s => document.querySelector(s);
const main = $("#main");
const esc = s => String(s ?? "").replace(/[&<>"]/g, m => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[m]));
const fmt = n => n == null ? "–" : new Intl.NumberFormat("de-DE").format(n);
const hm = d => new Intl.DateTimeFormat("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Berlin" }).format(new Date(d));
function ago(t) { const m = Math.round((Date.now() - new Date(t)) / 60000); return m < 1 ? "gerade" : m < 60 ? `vor ${m} Min` : m < 1440 ? `vor ${Math.round(m / 60)} Std` : `vor ${Math.round(m / 1440)} T`; }

const S = { depts: [], hasToken: false, runs: [], status: null, comments: [], accounts: [], clips: [], orders: null, view: "home", arg: null, flash: null };
const wf = r => (r.path || "").split("/").pop();

/* ------------------------------------------------------------ Daten */
async function loadRuns() { const r = await bridge.fetch(`${API}/actions/runs?per_page=100`); if (r && r.workflow_runs) S.runs = r.workflow_runs; }
async function loadPages() {
  const [s, c, a, cl] = await Promise.all(["status", "comments", "accounts", "cliplab"].map(n => bridge.fetch(`${PAGES}/${n}.json?t=${Date.now() / 60000 | 0}`)));
  if (s && s.channels) S.status = s;
  if (c && c.items) S.comments = c.items;
  if (a && a.accounts) S.accounts = a.accounts;
  if (Array.isArray(cl)) S.clips = cl;
}
async function loadOrders() { const o = await bridge.orders(); S.orders = o; }
function failingWorkflows() {           // letzter Lauf je Workflow fehlgeschlagen (letzte 36 h)
  const seen = {}, out = [];
  for (const r of S.runs) {
    const k = wf(r); if (seen[k] || r.status !== "completed") continue; seen[k] = 1;
    if (r.conclusion === "failure" && Date.now() - new Date(r.updated_at) < 36 * 3600e3) out.push(r);
  }
  return out;
}
const pendingClips = () => S.clips.filter(c => c.status === "pending");
const openOrders = () => (S.orders && S.orders.items || []).filter(o => o.state === "open");
const askOrders = () => openOrders().filter(o => o.labels.includes("rückfrage"));
const badAccounts = () => S.accounts.filter(a => a.state === "err");
function badges() {
  const set = (id, n, err) => { const b = $(id); b.textContent = n || ""; b.classList.toggle("err", !!err); };
  set("#n-approve", pendingClips().length + S.comments.length);
  set("#n-orders", askOrders().length || "", true);
  set("#n-acc", badAccounts().length, true);
}

/* ------------------------------------------------------------ Navigation */
function go(view, arg) {
  S.view = view; S.arg = arg ?? null; S.flash = null;
  document.querySelectorAll(".nav").forEach(b => b.classList.toggle("on", b.dataset.v === view && (view !== "dept" || b.dataset.a === arg)));
  render(); main.focus();
}
document.querySelectorAll(".nav[data-v]").forEach(b => b.addEventListener("click", () => go(b.dataset.v, b.dataset.a)));
function render() {
  badges();
  ({ home, orders, order, approve, accounts, dept, settings })[S.view]();
}
const flashHtml = () => S.flash ? `<p class="msg ${S.flash.ok ? "ok" : "err"}">${esc(S.flash.text)}</p>` : "";
const projOpts = sel => [["", "Allgemein"], ...S.depts.map(d => [d.id, d.name])].map(([v, t]) => `<option value="${v}" ${v === sel ? "selected" : ""}>${esc(t)}</option>`).join("");

/* ------------------------------------------------------------ Auftrag geben (überall gleich) */
function orderBox(proj) {
  return `<div class="order"><textarea id="o-text" placeholder="Was soll erledigt werden? z. B. „Mach 2 Clips aus dem IShowSpeed-Stream und reich sie ein“" aria-label="Auftrag"></textarea>
    <select id="o-proj" aria-label="Projekt">${projOpts(proj || "")}</select><button class="btn main" id="o-send">Auftrag geben</button></div>
    <p class="muted" style="margin:6px 2px 0;font-size:12.5px">Wird stündlich von Claude erledigt. Bei Geld, Löschen oder Rechtlichem kommt vorher eine Rückfrage.</p>`;
}
function wireOrderBox() {
  const b = $("#o-send"); if (!b) return;
  b.addEventListener("click", async () => {
    const t = $("#o-text").value.trim(); if (!t) return;
    b.disabled = true;
    const r = await bridge.orderCreate(t.split("\n")[0].slice(0, 90), t, $("#o-proj").value);
    S.flash = r.ok ? { ok: true, text: `Auftrag #${r.number} angelegt – wird bei der nächsten vollen Stunde erledigt.` } : { ok: false, text: r.msg };
    if (r.ok) { await loadOrders(); }
    render();
  });
}

/* ------------------------------------------------------------ Übersicht */
function home() {
  const fails = failingWorkflows(), clips = pendingClips(), asks = askOrders(), bad = badAccounts();
  const running = S.runs.filter(r => r.status !== "completed");
  const subs = S.status ? S.status.channels.reduce((a, c) => a + ((c.yt && c.yt.subs) || 0), 0) : null;
  const igf = S.status ? Object.values(S.status.instagram || {}).reduce((a, c) => a + (c.followers || 0), 0) : null;
  const today = new Date().toISOString().slice(0, 10), tr = S.runs.filter(r => r.created_at.startsWith(today));
  const need = [];
  asks.forEach(o => need.push(`<div class="row"><span class="dot warn"></span><span class="grow"><b>Rückfrage zu Auftrag #${o.number}</b><br><small>${esc(o.title)}</small></span><button class="btn" data-order="${o.number}">Antworten</button></div>`));
  if (clips.length) need.push(`<div class="row"><span class="dot warn"></span><span class="grow"><b>${clips.length} Clip${clips.length > 1 ? "s" : ""} zur Freigabe</b><br><small>The Clip Lab</small></span><button class="btn" data-go="approve">Ansehen</button></div>`);
  if (S.comments.length) need.push(`<div class="row"><span class="dot warn"></span><span class="grow"><b>${S.comments.length} Kommentar-Antworten vorgeschlagen</b><br><small>YouTube & Instagram</small></span><button class="btn" data-go="approve">Ansehen</button></div>`);
  bad.forEach(a => need.push(`<div class="row"><span class="dot err"></span><span class="grow"><b>${esc(a.platform)}: ${esc(a.name)}</b><br><small>${esc(a.note || "Problem")}</small></span><button class="btn" data-go="accounts">Konten</button></div>`));
  fails.forEach(r => need.push(`<div class="row"><span class="dot err"></span><span class="grow"><b>Fehlgeschlagen: ${esc(r.name)}</b><br><small>${esc(r.display_title)} · ${ago(r.updated_at)}</small></span><button class="btn" data-url="${esc(r.html_url)}">Details</button></div>`));
  const recent = (S.orders && S.orders.items || []).slice(0, 5);
  main.innerHTML = `<h1>Guten ${new Date().getHours() < 11 ? "Morgen" : new Date().getHours() < 18 ? "Tag" : "Abend"}</h1>
    <p class="sub">${need.length ? `${need.length} Punkt${need.length > 1 ? "e brauchen" : " braucht"} dich.` : "Alles läuft – nichts braucht dich gerade."}</p>
    ${orderBox()}${flashHtml()}
    <h2>Braucht dich</h2><div class="card need">${need.join("") || `<p class="empty">Nichts offen. 👍</p>`}</div>
    <h2>Zahlen</h2><div class="kpis">
      <div class="card kpi"><small>YouTube-Abos</small><b>${fmt(subs)}</b></div>
      <div class="card kpi"><small>Instagram-Follower</small><b>${fmt(igf)}</b></div>
      <div class="card kpi"><small>Abläufe heute</small><b>${tr.length}</b></div>
      <div class="card kpi"><small>Fehler heute</small><b style="color:${tr.some(r => r.conclusion === "failure") ? "var(--err)" : "inherit"}">${tr.filter(r => r.conclusion === "failure").length}</b></div>
      <div class="card kpi"><small>Konten verbunden</small><b>${S.accounts.filter(a => a.state === "ok").length}/${S.accounts.length || "–"}</b></div></div>
    <h2>Läuft gerade</h2><div class="card">${running.map(r => `<div class="row"><span class="dot busy"></span><span class="grow">${esc(r.name)}<br><small>${esc(r.display_title)} · seit ${ago(r.run_started_at || r.created_at).replace("vor ", "")}</small></span></div>`).join("") || `<p class="empty">Gerade läuft nichts.</p>`}</div>
    <h2>Letzte Aufträge</h2><div class="card">${recent.map(orderRow).join("") || `<p class="empty">${S.orders && S.orders.error ? esc(S.orders.error) : "Noch keine Aufträge."}</p>`}</div>`;
  wireCommon(); wireOrderBox();
}
function orderRow(o) {
  const st = o.state === "closed" ? ["ok", "erledigt"] : o.labels.includes("rückfrage") ? ["warn", "Rückfrage"] : o.labels.includes("in-arbeit") ? ["busy", "in Arbeit"] : ["", "wartet"];
  return `<div class="row card-row" data-order="${o.number}" style="cursor:pointer"><span class="grow"><b>#${o.number} ${esc(o.title)}</b><br><small>${esc(o.project || "Allgemein")} · ${ago(o.created_at)}${o.comments ? ` · ${o.comments} Antwort${o.comments > 1 ? "en" : ""}` : ""}</small></span><span class="pill ${st[0]}">${st[1]}</span></div>`;
}
function wireCommon() {
  main.querySelectorAll("[data-go]").forEach(b => b.addEventListener("click", () => go(b.dataset.go)));
  main.querySelectorAll("[data-order]").forEach(b => b.addEventListener("click", () => go("order", +b.dataset.order)));
  main.querySelectorAll("[data-url]").forEach(b => b.addEventListener("click", () => bridge.open(b.dataset.url)));
}

/* ------------------------------------------------------------ Aufträge */
function orders() {
  const all = (S.orders && S.orders.items) || [];
  main.innerHTML = `<h1>Aufträge</h1><p class="sub">Freitext-Anweisungen an dein Team. Claude arbeitet sie stündlich ab und antwortet hier.</p>
    ${orderBox()}${flashHtml()}
    <h2>Offen</h2><div class="card">${all.filter(o => o.state === "open").map(orderRow).join("") || `<p class="empty">${S.orders && S.orders.error ? esc(S.orders.error) : "Keine offenen Aufträge."}</p>`}</div>
    <h2>Erledigt</h2><div class="card">${all.filter(o => o.state === "closed").slice(0, 15).map(orderRow).join("") || `<p class="empty">–</p>`}</div>`;
  wireCommon(); wireOrderBox();
}
async function order() {
  main.innerHTML = `<p class="muted">Lade Auftrag #${S.arg} …</p>`;
  const t = await bridge.thread(S.arg);
  if (t.error) { main.innerHTML = `<p class="msg err">${esc(t.error)}</p>`; return; }
  main.innerHTML = `<button class="btn" data-go="orders">← Aufträge</button>
    <h1 style="margin-top:14px">#${t.number} ${esc(t.title)}</h1><p class="sub">${t.state === "closed" ? "Erledigt" : "Offen"} · ${hm(t.created_at)}</p>
    <div class="thread me">${esc(t.body)}</div>
    ${t.comments.map(c => `<div class="thread ${c.mine ? "me" : "bot"}"><small class="muted">${c.mine ? "Du" : "Claude"} · ${hm(c.created_at)}</small><br>${esc(c.body)}</div>`).join("")}
    ${flashHtml()}
    <div class="order" style="margin-top:12px"><textarea id="r-text" placeholder="Antwort oder Ergänzung …" aria-label="Antwort"></textarea><button class="btn main" id="r-send">Senden</button></div>`;
  wireCommon();
  $("#r-send").addEventListener("click", async () => {
    const v = $("#r-text").value.trim(); if (!v) return;
    const r = await bridge.reply(S.arg, v);
    S.flash = r.ok ? { ok: true, text: "Gesendet – Claude liest es beim nächsten Durchlauf." } : { ok: false, text: r.msg };
    await loadOrders(); order();
  });
}

/* ------------------------------------------------------------ Freigaben */
function approve() {
  const clips = pendingClips();
  main.innerHTML = `<h1>Freigaben</h1><p class="sub">Nichts geht raus, bevor du es hier freigibst.</p>${flashHtml()}
    <h2>Clips · The Clip Lab</h2>
    ${clips.map(c => `<div class="card clip" style="margin-bottom:12px"><video src="${esc(c.video)}" poster="${esc(c.thumb || "")}" controls preload="none"></video>
      <div><b>${esc(c.campaign_name)}</b> <span class="muted">· ${Math.round(c.duration)} s · ${ago(c.created)}</span>
      <p class="muted" style="margin:4px 0 8px">Geht zur US-Abendzeit raus auf: ${esc((c.platforms || []).join(", "))}</p>
      <textarea id="cap-${esc(c.id)}" aria-label="Caption">${esc(c.caption)}</textarea>
      <div style="display:flex;gap:8px;margin-top:10px"><button class="btn main" data-ok="${esc(c.id)}">Freigeben</button><button class="btn bad" data-no="${esc(c.id)}">Verwerfen</button></div></div></div>`).join("")
      || `<div class="card"><p class="empty">Keine Clips offen.</p></div>`}
    <h2>Kommentar-Antworten</h2><div class="card">${S.comments.slice(0, 12).map(c => `<div class="row"><span class="grow"><b>${esc(c.author)}</b> · <small>${esc(c.ch)}</small><br>${esc(c.text)}<br><small>Vorschlag: ${esc(c.reply || c.reason || "–")}</small></span></div>`).join("") || `<p class="empty">Keine offen.</p>`}
      ${S.comments.length ? `<p style="margin:10px 0 0"><button class="btn" data-url="${PAGES}/">Im Kanal-Studio freigeben</button></p>` : ""}</div>`;
  wireCommon();
  main.querySelectorAll("[data-ok]").forEach(b => b.addEventListener("click", async () => {
    const id = b.dataset.ok, orig = S.clips.find(c => c.id === id), cap = $("#cap-" + CSS.escape(id)).value;
    b.disabled = true;
    const r = await bridge.clip([id], "approve", cap !== orig.caption ? { [id]: cap } : {});
    S.flash = r.ok ? { ok: true, text: "Freigegeben – wird zur US-Abendzeit gepostet und eingereicht." } : { ok: false, text: r.msg };
    if (r.ok) orig.status = "approved"; render();
  }));
  main.querySelectorAll("[data-no]").forEach(b => b.addEventListener("click", async () => {
    const id = b.dataset.no; b.disabled = true;
    const r = await bridge.clip([id], "reject");
    S.flash = r.ok ? { ok: true, text: "Verworfen." } : { ok: false, text: r.msg };
    if (r.ok) S.clips.find(c => c.id === id).status = "rejected"; render();
  }));
}

/* ------------------------------------------------------------ Konten */
function accounts() {
  const pill = a => ({ ok: ["ok", "verbunden"], err: ["err", "Problem"], off: ["", "nicht verbunden"], chrome: ["chrome", "über Chrome"], unknown: ["", "unbekannt"] })[a.state] || ["", a.state];
  const groups = {};
  S.accounts.forEach(a => (groups[a.platform] = groups[a.platform] || []).push(a));
  main.innerHTML = `<h1>Konten</h1><p class="sub">Alle verbundenen Konten. Passwörter und Schlüssel liegen nie hier – nur der Status.</p>
    ${Object.entries(groups).map(([p, list]) => `<h2>${esc(p)}</h2><div class="card">${list.map(a => { const [c, t] = pill(a);
      return `<div class="row"><span class="dot ${c === "chrome" ? "plan" : c}"></span><span class="grow"><b>${esc(a.account || a.name)}</b><br><small>${esc(a.project || "")}${a.note ? " · " + esc(a.note) : ""}</small></span><span class="pill ${c}">${t}</span></div>`; }).join("")}</div>`).join("")
      || `<div class="card"><p class="empty">Noch keine Daten – das Studio aktualisiert alle 30 Minuten.</p></div>`}
    <p class="muted" style="margin-top:14px">„Über Chrome“ heißt: Claude erledigt es in deinem Chrome (mit deinen Anmeldungen) – dafür muss der PC an und Chrome offen sein.</p>`;
}

/* ------------------------------------------------------------ Projekt */
function dept() {
  const d = S.depts.find(x => x.id === S.arg); if (!d) return home();
  const watch = new Set(d.team.flatMap(w => w.watch || []));
  const rr = S.runs.filter(r => watch.has(wf(r))).slice(0, 8);
  const pod = (S.orders && S.orders.items || []).filter(o => o.project === d.id).slice(0, 6);
  main.innerHTML = `<h1>${esc(d.name)}</h1><p class="sub">${esc(d.sub)}</p>${orderBox(d.id)}${flashHtml()}
    <h2>Team</h2><div class="grid">${d.team.map(w => `<div class="card"><b>${esc(w.name)}</b> <span class="muted">· ${esc(w.role)}</span><p class="muted" style="margin:2px 0 8px">${esc(w.job)}</p>
      ${(w.jobs || []).map(j => `<button class="btn" style="margin:0 6px 6px 0" data-job="${esc(j.id)}" data-ext="${j.external ? 1 : ""}" title="${esc(j.hint || "")}">${esc(j.label)}${j.external ? " ↗" : ""}</button>`).join("") || `<small class="muted">Aufgaben per Freitext-Auftrag.</small>`}</div>`).join("")}</div>
    <h2>Letzte Abläufe</h2><div class="card">${rr.map(r => `<div class="row"><span class="dot ${r.status !== "completed" ? "busy" : r.conclusion === "success" ? "ok" : r.conclusion === "failure" ? "err" : ""}"></span><span class="grow">${esc(r.display_title)}<br><small>${esc(r.name)} · ${ago(r.created_at)}</small></span><button class="btn" data-url="${esc(r.html_url)}">↗</button></div>`).join("") || `<p class="empty">Noch keine.</p>`}</div>
    ${pod.length ? `<h2>Aufträge</h2><div class="card">${pod.map(orderRow).join("")}</div>` : ""}`;
  wireCommon(); wireOrderBox();
  main.querySelectorAll("[data-job]").forEach(b => b.addEventListener("click", async () => {
    if (b.dataset.ext && !confirmInline(b)) return;
    b.disabled = true;
    const r = await bridge.dispatch(b.dataset.job, !!b.dataset.ext);
    S.flash = r.ok ? { ok: true, text: `„${b.textContent.replace(" ↗", "")}“ gestartet.` } : { ok: false, text: r.msg };
    setTimeout(async () => { await loadRuns(); if (S.view === "dept") render(); }, 9000); render();
  }));
}
function confirmInline(b) {      // zweiter Klick bestätigt Handgriffe, die nach außen wirken (kein Browser-Dialog)
  if (b.dataset.armed) return true;
  b.dataset.armed = 1; b.textContent = "Wirkt nach außen – nochmal klicken zum Starten"; b.classList.add("main");
  setTimeout(() => { if (b.isConnected && b.dataset.armed) render(); }, 6000);
  return false;
}

/* ------------------------------------------------------------ Einstellungen */
function settings() {
  main.innerHTML = `<h1>Einstellungen</h1><p class="sub">${inApp() ? "Programm" : "Browser-Vorschau – nur lesend"}</p>${flashHtml()}
    <div class="card"><b>GitHub-Schlüssel</b><p class="muted">${S.hasToken ? "Hinterlegt ✓ – sicher in der Windows-Anmeldeinformationsverwaltung." : "Nötig für Aufträge, Freigaben und Handgriffe (beginnt mit github_pat_). Braucht: Actions (youtube-automatik) und Issues (cicco-zentrale)."}</p>
      <div class="field"><input id="tok" type="password" autocomplete="off" placeholder="github_pat_…" aria-label="GitHub-Schlüssel"></div>
      <div style="display:flex;gap:8px"><button class="btn main" id="tok-save">Speichern</button>${S.hasToken ? `<button class="btn" id="tok-del">Entfernen</button>` : ""}</div></div>`;
  $("#tok-save").addEventListener("click", async () => {
    const r = await bridge.setToken($("#tok").value);
    S.flash = r.ok ? { ok: true, text: "Gespeichert." } : { ok: false, text: r.msg }; if (r.ok) S.hasToken = true; settings();
  });
  const del = $("#tok-del"); if (del) del.addEventListener("click", async () => { await bridge.clearToken(); S.hasToken = false; S.flash = { ok: true, text: "Entfernt." }; settings(); });
}

/* ------------------------------------------------------------ Start */
async function start() {
  const cat = await bridge.catalog();
  S.depts = cat.depts || []; S.hasToken = !!cat.has_token;
  $("#projnav").innerHTML = S.depts.map(d => `<button class="nav" data-v="dept" data-a="${d.id}"><span class="dot ${d.state === "live" ? "ok" : d.state === "warn" ? "warn" : "plan"}" style="margin:0 5px"></span>${esc(d.name)}</button>`).join("");
  document.querySelectorAll("#projnav .nav").forEach(b => b.addEventListener("click", () => go("dept", b.dataset.a)));
  $("#mode").textContent = inApp() ? (S.hasToken ? "verbunden" : "nur lesend – Schlüssel fehlt") : "Browser-Vorschau";
  render();
  await Promise.all([loadRuns(), loadPages(), loadOrders()]);
  render();
  setInterval(async () => { await loadRuns(); if (["home", "dept"].includes(S.view) && !document.activeElement.matches("textarea,input")) render(); else badges(); }, 45000);
  setInterval(async () => { await Promise.all([loadPages(), loadOrders()]); badges(); }, 300000);
}
let started = false;
const boot = () => { if (!started) { started = true; start(); } };
if (inApp()) boot(); else { addEventListener("pywebviewready", boot); setTimeout(boot, 500); }
