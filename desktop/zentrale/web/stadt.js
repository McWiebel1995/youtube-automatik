"use strict";
/* Cicco Zentrale – Oberfläche. Läuft im Programm (window.pywebview.api) oder zum Testen im Browser (nur lesend). */
const REPO = "McWiebel1995/youtube-automatik";
const API = `https://api.github.com/repos/${REPO}`;
const PAGES = "https://mcwiebel1995.github.io/youtube-automatik";
const LAYOUT = {
  media:   { pos:[-6,0,-3],    size:[5.8,4.2,4.6], color:0x5a4ea8, roof:0x7a6fd0 },
  shop:    { pos:[2.2,0,-6.2], size:[4.4,3.2,3.8], color:0x3b4a2f, roof:0x55683f },
  cicco:   { pos:[7.4,0,-1],   size:[3.8,2.6,3.4], color:0x8a5a2b, roof:0xb0743a },
  kdp:     { pos:[-1,0,4.8],   size:[3.6,3,3.2],   color:0x2d5d6e, roof:0x3f8096 },
  finance: { pos:[5.6,0,4.6],  size:[4,3.6,3.4],   color:0x6b6f7a, roof:0x9097a6 },
  legal:   { pos:[1.6,0,1.6],  size:[3.4,2.8,3],   color:0x4a3a5c, roof:0x6c568a },
  lab:     { pos:[-6.8,0,4],   size:[3,2.2,3],     color:0x7a3e6a, roof:0xa4558e },
  engine:  { pos:[-2,0,-0.4],  size:[2.6,1.8,2.6], color:0x3a3f52, roof:0x5b6380 },
  cliplab: { pos:[-9.6,0,-0.6], size:[3.2,2.6,3],  color:0x8a4a2e, roof:0xc06a3c },
  gaming:  { pos:[9.6,0,2.4],   size:[3,2.4,2.8],  color:0x2b4f7a, roof:0x3f74b0 },
};
const inApp = () => !!(window.pywebview && window.pywebview.api);
const bridge = {
  async catalog() { return inApp() ? pywebview.api.catalog() : { depts: await (await fetch("catalog.json")).json(), has_token:false }; },
  async fetch(url) {
    if (inApp()) return pywebview.api.fetch(url);
    try { const r = await fetch(url); return r.ok ? r.json() : { error:"HTTP " + r.status }; } catch (e) { return { error:String(e) }; }
  },
  async dispatch(id, approved) { return inApp() ? pywebview.api.dispatch(id, approved) : { ok:false, msg:"Nur im Programm möglich (Browser-Vorschau)" }; },
  async tasks() { if (inApp()) return pywebview.api.tasks(); try { return JSON.parse(localStorage.getItem("cz-tasks")) || []; } catch { return []; } },
  async saveTasks(t) { if (inApp()) return pywebview.api.save_tasks(t); try { localStorage.setItem("cz-tasks", JSON.stringify(t)); } catch {} },
  async setToken(t) { return inApp() ? pywebview.api.set_token(t) : { ok:false, msg:"Nur im Programm möglich" }; },
  async clearToken() { return inApp() ? pywebview.api.clear_token() : true; },
  open(url) { if (inApp()) pywebview.api.open(url); else window.open(url, "_blank", "noopener"); },
};
const pickables = [], byId = {};
let DEPTS = [];
/* ------------------------------------------------------------ Szene */
const canvas = document.getElementById("scene");
const renderer = new THREE.WebGLRenderer({ canvas, antialias:true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputEncoding = THREE.sRGBEncoding;
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x141a30);
scene.fog = new THREE.Fog(0x141a30, 40, 72);
const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 200);
const HOME = new THREE.Vector3(22, 20, 22);
camera.position.copy(HOME);
const controls = new THREE.OrbitControls(camera, canvas);
Object.assign(controls, { enableDamping:true, dampingFactor:.08, maxPolarAngle:Math.PI * .44, minDistance:7, maxDistance:48, enablePan:false });

scene.add(new THREE.HemisphereLight(0x8fa0ff, 0x2a1d2e, .55));
const sun = new THREE.DirectionalLight(0xffc89a, 1.15);
sun.position.set(-14, 18, 8); sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, { left:-16, right:16, top:16, bottom:-16, near:1, far:60 });
scene.add(sun);

const island = new THREE.Mesh(new THREE.CylinderGeometry(15, 13, 2.2, 7), new THREE.MeshStandardMaterial({ color:0x3d5a3a, roughness:.95, flatShading:true }));
island.position.y = -1.1; island.receiveShadow = true; scene.add(island);
const cliff = new THREE.Mesh(new THREE.CylinderGeometry(13, 9, 4, 7), new THREE.MeshStandardMaterial({ color:0x5b4636, roughness:1, flatShading:true }));
cliff.position.y = -4.2; scene.add(cliff);
const water = new THREE.Mesh(new THREE.CircleGeometry(80, 48), new THREE.MeshStandardMaterial({ color:0x1b2c4f, roughness:.35, metalness:.2 }));
water.rotation.x = -Math.PI / 2; water.position.y = -3.2; scene.add(water);
const pathMat = new THREE.MeshStandardMaterial({ color:0x8c7c63, roughness:1 });
function path(a, b) {
  const dx = b[0] - a[0], dz = b[2] - a[2], len = Math.hypot(dx, dz);
  const m = new THREE.Mesh(new THREE.BoxGeometry(len, .05, .9), pathMat);
  m.position.set((a[0] + b[0]) / 2, .02, (a[2] + b[2]) / 2); m.rotation.y = -Math.atan2(dz, dx); m.receiveShadow = true; scene.add(m);
}
Object.entries(LAYOUT).forEach(([id, l]) => id !== "engine" && path([-2, 0, -0.4], l.pos));
const rnd = (s => () => (s = (s * 16807) % 2147483647) / 2147483647)(42);
const treeMat = new THREE.MeshStandardMaterial({ color:0x2f6b45, flatShading:true, roughness:1 });
const trunkMat = new THREE.MeshStandardMaterial({ color:0x5a3d2b });
for (let i = 0; i < 46; i++) {
  const a = rnd() * Math.PI * 2, r = 10 + rnd() * 3.2, h = .9 + rnd() * .9, t = new THREE.Group();
  const cone = new THREE.Mesh(new THREE.ConeGeometry(.55 + rnd() * .3, h * 1.6, 6), treeMat); cone.position.y = h * .8 + .4; cone.castShadow = true;
  const tr = new THREE.Mesh(new THREE.CylinderGeometry(.08, .1, .5), trunkMat); tr.position.y = .25;
  t.add(cone, tr); t.position.set(Math.cos(a) * r, 0, Math.sin(a) * r); scene.add(t);
}
[[0,0,-3.2],[3.4,0,-0.8],[-4,0,2],[2,0,4.2],[6,0,-4],[-6,0,0.6]].forEach(p => {
  const pole = new THREE.Mesh(new THREE.CylinderGeometry(.05, .05, 1.6), new THREE.MeshStandardMaterial({ color:0x333844 }));
  pole.position.set(p[0], .8, p[2]); scene.add(pole);
  const bulb = new THREE.Mesh(new THREE.SphereGeometry(.14, 12, 8), new THREE.MeshBasicMaterial({ color:0xffd28a }));
  bulb.position.set(p[0], 1.65, p[2]); scene.add(bulb);
  const l = new THREE.PointLight(0xffb866, .9, 6, 2); l.position.copy(bulb.position); scene.add(l);
});

/* ------------------------------------------------------------ Gebäude mit Innenleben */
const winTex = (() => {
  const c = document.createElement("canvas"); c.width = 128; c.height = 128; const g = c.getContext("2d");
  g.fillStyle = "#000"; g.fillRect(0, 0, 128, 128);
  for (let y = 10; y < 120; y += 22) for (let x = 10; x < 120; x += 20) {
    g.fillStyle = rnd() < .72 ? `hsl(${36 + rnd() * 12},95%,${58 + rnd() * 18}%)` : "#111"; g.fillRect(x, y, 11, 13);
  }
  const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; return t;
})();
const deskMat = new THREE.MeshStandardMaterial({ color:0x7a5a40, roughness:.9 });
const floorMat = new THREE.MeshStandardMaterial({ color:0xb9a98f, roughness:1 });
const wallInMat = new THREE.MeshStandardMaterial({ color:0xe8e1d4, roughness:1 });

function makeWorker(color) {
  const g = new THREE.Group();
  const body = new THREE.Mesh(new THREE.CylinderGeometry(.16, .2, .5, 10), new THREE.MeshStandardMaterial({ color, roughness:.6 }));
  body.position.y = .55;
  const head = new THREE.Mesh(new THREE.SphereGeometry(.15, 14, 10), new THREE.MeshStandardMaterial({ color:0xf1c9a5, roughness:.7 }));
  head.position.y = .93;
  const chair = new THREE.Mesh(new THREE.BoxGeometry(.4, .06, .4), new THREE.MeshStandardMaterial({ color:0x333844 }));
  chair.position.y = .3;
  g.add(chair, body, head); g.userData = { body, head };
  return g;
}

function buildDept(d) {
  Object.assign(d, LAYOUT[d.id] || { pos:[0, 0, 9 + Object.keys(byId).length], size:[3, 2.4, 3], color:0x555a70, roof:0x7a7f99 });
  const g = new THREE.Group(); g.position.set(d.pos[0], 0, d.pos[2]);
  const [w, h, dep] = d.size;
  const em = winTex.clone(); em.needsUpdate = true; em.repeat.set(w / 1.6, h / 1.4);
  const shell = new THREE.MeshStandardMaterial({ color:d.color, roughness:.7, flatShading:true, emissive:0xffffff, emissiveMap:em,
    emissiveIntensity: d.state === "plan" ? .25 : .8, transparent:true, opacity:1 });
  const body = new THREE.Mesh(new THREE.BoxGeometry(w, h, dep), shell); body.position.y = h / 2; body.castShadow = body.receiveShadow = true;
  const roofMat = new THREE.MeshStandardMaterial({ color:d.roof, flatShading:true, transparent:true, opacity:1 });
  const roof = new THREE.Mesh(new THREE.BoxGeometry(w + .3, .35, dep + .3), roofMat); roof.position.y = h + .17; roof.castShadow = true;
  const base = new THREE.Mesh(new THREE.BoxGeometry(w + 1, .18, dep + 1), new THREE.MeshStandardMaterial({ color:0x6e6a64 })); base.position.y = .09; base.receiveShadow = true;
  g.add(base, body, roof);

  // Innenraum: Boden, Trennwände, Schreibtische mit Mitarbeitern (zuerst unsichtbar)
  const inside = new THREE.Group(); inside.visible = false;
  const fl = new THREE.Mesh(new THREE.BoxGeometry(w - .2, .06, dep - .2), floorMat); fl.position.y = .2; fl.receiveShadow = true; inside.add(fl);
  const back = new THREE.Mesh(new THREE.BoxGeometry(w - .2, 1.6, .08), wallInMat); back.position.set(0, 1, -dep / 2 + .14); inside.add(back);
  const side = new THREE.Mesh(new THREE.BoxGeometry(.08, 1.6, dep - .2), wallInMat); side.position.set(-w / 2 + .14, 1, 0); inside.add(side);
  const n = d.team.length, cols = Math.min(3, n), rows = Math.ceil(n / cols);
  d.workers = d.team.map((tm, i) => {
    const { name, role, job } = tm, col = parseInt(tm.color.slice(1), 16);
    const cx = (i % cols - (cols - 1) / 2) * ((w - 1) / Math.max(cols, 1)), cz = (Math.floor(i / cols) - (rows - 1) / 2) * ((dep - 1.2) / Math.max(rows, 1));
    const desk = new THREE.Mesh(new THREE.BoxGeometry(.9, .06, .5), deskMat); desk.position.set(cx, .62, cz - .25); desk.castShadow = true;
    const scrMat = new THREE.MeshBasicMaterial({ color:0x2c6b9e });
    const scr = new THREE.Mesh(new THREE.BoxGeometry(.5, .32, .03), scrMat); scr.position.set(cx, .85, cz - .4);
    const wk = makeWorker(col); wk.position.set(cx, 0, cz + .15); wk.rotation.y = Math.PI;
    inside.add(desk, scr, wk);
    // kleine Trennwand zwischen den Plätzen
    if (i % cols) { const p = new THREE.Mesh(new THREE.BoxGeometry(.05, .7, .9), wallInMat); p.position.set(cx - (w - 1) / cols / 2, .55, cz - .1); inside.add(p); }
    return { ...tm, colorInt:col, mesh:wk, scr:scrMat, state:"frei", progress:0, run:null, anchor:new THREE.Vector3() };
  });
  g.add(inside);

  // Erkennungsmerkmal
  if (d.id === "media") {
    const mast = new THREE.Mesh(new THREE.CylinderGeometry(.07, .12, 3), new THREE.MeshStandardMaterial({ color:0x9aa0b8 }));
    mast.position.set(w / 2 - .7, h + 1.8, 0); g.add(mast); d.extra = [mast];
    const bea = new THREE.Mesh(new THREE.SphereGeometry(.18, 12, 8), new THREE.MeshBasicMaterial({ color:0xff5a5a })); bea.position.set(w / 2 - .7, h + 3.35, 0); g.add(bea); d.beacon = bea; d.extra.push(bea);
  } else if (d.id === "kdp") {
    d.extra = [0x9c3d3d, 0xd9b44a, 0x3d6f9c].map((c, k) => { const b = new THREE.Mesh(new THREE.BoxGeometry(1.2, .28, .85), new THREE.MeshStandardMaterial({ color:c }));
      b.position.set(0, h + .5 + k * .29, 0); b.rotation.y = k * .35; g.add(b); return b; });
  } else if (d.id === "finance" || d.id === "legal") {
    d.extra = [-1, 0, 1].map(k => { const c = new THREE.Mesh(new THREE.CylinderGeometry(.14, .14, h * .8), new THREE.MeshStandardMaterial({ color:0xd8d3c4 }));
      c.position.set(k * (w / 3.2), h * .4, dep / 2 + .25); g.add(c); return c; });
  } else if (d.id === "lab") {
    const dome = new THREE.Mesh(new THREE.SphereGeometry(1.2, 16, 10, 0, Math.PI * 2, 0, Math.PI / 2), new THREE.MeshStandardMaterial({ color:0xc9b6ff, emissive:0x6a4fd0, emissiveIntensity:.35 }));
    dome.position.y = h + .35; g.add(dome); d.extra = [dome];
  } else if (d.id === "engine") {
    const gear = new THREE.Mesh(new THREE.TorusGeometry(.75, .22, 6, 10), new THREE.MeshStandardMaterial({ color:0x8be08b, emissive:0x2c6b2c, emissiveIntensity:.6 }));
    gear.position.y = h + .9; g.add(gear); d.gear = gear; d.extra = [gear];
  } else if (d.id === "cicco") {
    const ol = new THREE.Mesh(new THREE.DodecahedronGeometry(.9), new THREE.MeshStandardMaterial({ color:0x8a9a5b, flatShading:true }));
    ol.position.set(-w / 2 - .4, 1.5, dep / 2 + .3); g.add(ol);
  } else if (d.id === "shop") {
    const aw = new THREE.Mesh(new THREE.BoxGeometry(w * .9, .12, 1), new THREE.MeshStandardMaterial({ color:0x6b7a45, flatShading:true }));
    aw.position.set(0, h * .55, dep / 2 + .5); aw.rotation.x = .25; g.add(aw);
  }
  body.userData.id = roof.userData.id = d.id;
  pickables.push(body, roof);
  scene.add(g);
  Object.assign(d, { group:g, shell, roofMesh:roof, roofMat, inside, h, open:0,
    top:new THREE.Vector3(d.pos[0], h + (d.id === "media" ? 3.9 : d.id === "kdp" ? 1.6 : d.id === "lab" ? 1.8 : 1.1), d.pos[2]) });
  byId[d.id] = d;
}

const fpos = new Float32Array(120 * 3);
for (let i = 0; i < 120; i++) { fpos[i * 3] = (rnd() - .5) * 26; fpos[i * 3 + 1] = .5 + rnd() * 6; fpos[i * 3 + 2] = (rnd() - .5) * 26; }
const fgeo = new THREE.BufferGeometry(); fgeo.setAttribute("position", new THREE.BufferAttribute(fpos, 3));
const flies = new THREE.Points(fgeo, new THREE.PointsMaterial({ color:0xffd98a, size:.09, transparent:true, opacity:.8 }));
scene.add(flies);

/* ------------------------------------------------------------ Zustand & Live-Daten */
const labels = document.getElementById("labels");
const panel = document.getElementById("panel");
const esc = s => String(s ?? "").replace(/[&<>"]/g, m => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;" }[m]));
const hm = d => new Intl.DateTimeFormat("de-DE", { hour:"2-digit", minute:"2-digit", timeZone:"Europe/Berlin" }).format(new Date(d));
let hasToken = false, runs = [], status = null, comments = [], tasks = [], view = null, sel = 0, pending = null, flash = null;

function ago(t) { const m = Math.round((Date.now() - new Date(t)) / 60000); return m < 1 ? "gerade" : m < 60 ? `vor ${m} Min` : m < 1440 ? `vor ${Math.round(m / 60)} Std` : `vor ${Math.round(m / 1440)} T`; }
function wfOf(r) { return (r.path || "").split("/").pop(); }
function workerRuns(w) { return runs.filter(r => (w.watch || []).includes(wfOf(r))); }
function refreshWorkers() {
  DEPTS.forEach(d => d.workers.forEach(w => {
    const rr = workerRuns(w), act = rr.find(r => r.status !== "completed"), last = rr.find(r => r.status === "completed");
    w.run = act || last || null;
    w.state = act ? "arbeitet" : (w.waitUntil && Date.now() < w.waitUntil) ? "startet" : last ? (last.conclusion === "success" ? "fertig" : last.conclusion === "failure" ? "Fehler" : "frei") : "frei";
    if (w.state === "fertig" && Date.now() - new Date(last.updated_at) > 6 * 3600e3) w.state = "frei";
    w.progress = act ? Math.min(95, (Date.now() - new Date(act.run_started_at || act.created_at)) / 60000 / (w.typical || 20) * 100) : 0;
  }));
}
async function loadRuns() {
  const r = await bridge.fetch(`${API}/actions/runs?per_page=80`);
  if (r && r.workflow_runs) { runs = r.workflow_runs; refreshWorkers(); kpis(); if (view && view.type === "dept") renderDept(); }
}
async function loadStatus() {
  const s = await bridge.fetch(`${PAGES}/status.json`); if (s && s.channels) status = s;
  const c = await bridge.fetch(`${PAGES}/comments.json`); if (c && c.items) comments = c.items;
  kpis();
}
function kpis() {
  const today = new Date().toISOString().slice(0, 10);
  const tr = runs.filter(r => r.created_at.startsWith(today));
  const subs = status ? status.channels.reduce((a, c) => a + ((c.yt && c.yt.subs) || 0), 0) : null;
  const igf = status ? Object.values(status.instagram || {}).reduce((a, c) => a + (c.followers || 0), 0) : null;
  const K = [["YouTube-Abos", subs ?? "–"], ["Instagram", igf ?? "–"], ["Läufe heute", tr.length],
             ["Fehler heute", tr.filter(r => r.conclusion === "failure").length]];
  document.getElementById("kpis").innerHTML = K.map(([k, v]) => `<div class="kpi"><small>${k}</small><b>${v}</b></div>`).join("");
  document.getElementById("ntasks").textContent = tasks.filter(t => !t.done).length;
  document.getElementById("ncomments").textContent = comments.length;
}

/* ------------------------------------------------------------ Panels */
function openPanel() { document.body.classList.add("panel-open"); panel.classList.add("open"); panel.setAttribute("aria-hidden", "false"); }
function closeAll() {
  view = null; focus = null; pending = null; document.body.classList.remove("panel-open"); panel.classList.remove("open"); panel.setAttribute("aria-hidden", "true");
  DEPTS.forEach(x => x.label.classList.remove("on", "dim"));
  tgtGoal = new THREE.Vector3(0, 0, 0); camGoal = HOME.clone();
}
function head(title, sub) {
  return `<div class="ph"><div><h2 id="ptitle">${esc(title)}</h2>${sub ? `<p>${esc(sub)}</p>` : ""}</div><button class="x" id="px" aria-label="Schließen">✕</button></div>`;
}
function wireClose() { panel.querySelector("#px").addEventListener("click", closeAll); }

function openDept(id) {
  const d = byId[id]; focus = id; sel = 0; pending = null; flash = null; view = { type:"dept", id };
  DEPTS.forEach(x => { x.label.classList.toggle("on", x.id === id); x.label.classList.toggle("dim", x.id !== id); });
  const t = new THREE.Vector3(d.pos[0], 1, d.pos[2]);
  tgtGoal = t; camGoal = t.clone().add(new THREE.Vector3(4.5, 9, 8));
  renderDept(); openPanel();
}
function selectWorker(id, i) { if (focus !== id) openDept(id); sel = i; pending = null; flash = null; renderDept(); }
function pillOf(w) {
  const cls = { arbeitet:"busy", startet:"busy", fertig:"ok", Fehler:"err" }[w.state] || "";
  return `<span class="pill ${cls}">${esc(w.state)}</span>`;
}
function renderDept() {
  const d = byId[view.id], w = d.workers[sel];
  const mine = tasks.filter(t => !t.done && (t.dept === d.id));
  let html = head(d.name, d.sub);
  html += `<div class="sec"><h3>Team</h3>${d.workers.map((x, i) => `<button class="worker ${i === sel ? "sel" : ""}" data-i="${i}">
      <span class="avatar" style="background:${x.color}">${esc(x.name[0])}</span>
      <span><b>${esc(x.name)} · ${esc(x.role)}</b><small>${esc(x.run && x.state === "arbeitet" ? x.run.display_title : x.job)}</small></span>
      ${pillOf(x)}${x.state === "arbeitet" ? `<span class="bar"><i style="width:${x.progress}%"></i></span>` : ""}</button>`).join("")}</div>`;
  html += `<div class="sec"><h3>Aufträge an ${esc(w.name)}</h3>`;
  if (flash) html += `<p class="msg ${flash.ok ? "ok" : "err"}">${esc(flash.text)}</p>`;
  if (pending) {
    const j = w.jobs.find(x => x.id === pending);
    html += `<div class="confirm"><b>Freigabe nötig</b><span>„${esc(j.label)}“ wirkt nach außen${j.hint ? " (" + esc(j.hint) + ")" : ""}. Wirklich starten?</span>
      <span class="row" style="display:flex;gap:8px"><button class="btn main" id="ok-go">Freigeben &amp; starten</button><button class="btn" id="ok-no">Abbrechen</button></span></div>`;
  } else if (w.jobs && w.jobs.length) {
    html += `<div class="jobs">${w.jobs.map(j => `<button class="jobbtn" data-j="${j.id}" ${w.state === "arbeitet" || w.state === "startet" ? "disabled" : ""}>
      <span>${esc(j.label)}${j.hint ? `<small>${esc(j.hint)}</small>` : ""}</span>${j.external ? `<span class="ext">Freigabe</span>` : ""}</button>`).join("")}</div>`;
    if (!hasToken) html += `<p class="note">Zum Starten brauchst du einmal deinen GitHub-Schlüssel (Einstellungen).</p>`;
  } else {
    html += `<p class="note">Für ${esc(w.name)} gibt es noch keine festen Handgriffe – die kommen mit dem Ausbau dieser Abteilung.</p>`;
  }
  html += `<div class="field" style="margin-top:10px"><label for="note-in" class="note">Notiz / Auftrag für später (landet in deinen Aufgaben)</label>
    <span style="display:flex;gap:8px"><input id="note-in" placeholder="z. B. Quiz über Vulkane testen" style="flex:1;min-width:0"><button class="btn" id="note-add">Merken</button></span></div></div>`;
  if (w.run) html += `<div class="sec"><h3>Letzter Lauf</h3><p class="note"><a href="#" id="runlink">${esc(w.run.display_title || w.run.name)}</a> · ${hm(w.run.created_at)} · ${esc(w.run.conclusion || w.run.status)}</p></div>`;
  if (mine.length) html += `<div class="sec"><h3>Offene Aufgaben dieser Abteilung</h3>${mine.map(taskRow).join("")}</div>`;
  if (d.id === "media" && status) {
    html += `<div class="sec"><h3>Kanäle</h3>${status.channels.filter(c => c.yt).map(c => `<div class="task"><span>▶</span><span>${esc(c.yt.title)}</span><small>${c.yt.subs} Abos</small></div>`).join("")}</div>`;
  }
  panel.innerHTML = html; wireClose();
  panel.querySelectorAll(".worker").forEach(b => b.addEventListener("click", () => { sel = +b.dataset.i; pending = null; flash = null; renderDept(); }));
  panel.querySelectorAll(".jobbtn").forEach(b => b.addEventListener("click", () => {
    const j = w.jobs.find(x => x.id === b.dataset.j);
    if (j.external) { pending = j.id; renderDept(); } else go(w, j, false);
  }));
  const okGo = panel.querySelector("#ok-go"); if (okGo) okGo.addEventListener("click", () => go(w, w.jobs.find(x => x.id === pending), true));
  const okNo = panel.querySelector("#ok-no"); if (okNo) okNo.addEventListener("click", () => { pending = null; renderDept(); });
  const rl = panel.querySelector("#runlink"); if (rl) rl.addEventListener("click", e => { e.preventDefault(); bridge.open(w.run.html_url); });
  panel.querySelector("#note-add").addEventListener("click", async () => {
    const v = panel.querySelector("#note-in").value.trim(); if (!v) return;
    tasks.push({ id:Date.now(), t:v, dept:d.id, who:w.name, done:false }); await bridge.saveTasks(tasks); kpis(); renderDept();
  });
  wireTasks();
}
async function go(w, j, approved) {
  pending = null; flash = { ok:true, text:"Wird gestartet …" }; renderDept();
  const r = await bridge.dispatch(j.id, approved);
  if (r.ok) { w.waitUntil = Date.now() + 90000; w.state = "startet"; flash = { ok:true, text:`„${j.label}“ läuft an – ${w.name} legt los.` }; setTimeout(loadRuns, 8000); setTimeout(loadRuns, 25000); }
  else flash = { ok:false, text:r.msg || "Konnte nicht starten" };
  renderDept();
}
function taskRow(t) {
  return `<div class="task ${t.done ? "done" : ""}"><input type="checkbox" data-t="${t.id}" ${t.done ? "checked" : ""} aria-label="erledigt"><span>${esc(t.t)}</span><small>${esc(t.who || "")}</small></div>`;
}
function wireTasks() {
  panel.querySelectorAll("input[data-t]").forEach(c => c.addEventListener("change", async () => {
    const t = tasks.find(x => String(x.id) === c.dataset.t); if (!t) return;
    t.done = c.checked; await bridge.saveTasks(tasks); kpis(); view.type === "tasks" ? renderTasks() : renderDept();
  }));
}
function renderTasks() {
  view = { type:"tasks" };
  const open = tasks.filter(t => !t.done), done = tasks.filter(t => t.done);
  panel.innerHTML = head("Aufgaben", `${open.length} offen · ${done.length} erledigt`) +
    `<div class="sec"><h3>Offen</h3>${open.map(taskRow).join("") || `<p class="note">Alles erledigt.</p>`}</div>` +
    (done.length ? `<div class="sec"><h3>Erledigt</h3>${done.slice(-10).map(taskRow).join("")}</div>` : "") +
    `<div class="sec field"><label for="t-new" class="note">Neue Aufgabe</label><span style="display:flex;gap:8px"><input id="t-new" style="flex:1;min-width:0"><button class="btn main" id="t-add">Hinzufügen</button></span></div>`;
  wireClose(); wireTasks();
  panel.querySelector("#t-add").addEventListener("click", async () => {
    const v = panel.querySelector("#t-new").value.trim(); if (!v) return;
    tasks.push({ id:Date.now(), t:v, dept:"", who:"du", done:false }); await bridge.saveTasks(tasks); kpis(); renderTasks();
  });
  openPanel();
}
function renderComments() {
  view = { type:"comments" };
  panel.innerHTML = head("Kommentare", `${comments.length} warten auf Freigabe`) +
    `<div class="sec">${comments.slice(0, 30).map(c => `<div class="task"><span>${c.pf === "yt" ? "▶" : "◎"}</span><span><b>${esc(c.author)}</b>: ${esc(c.text)}<br><small>${esc(c.ch)} · Vorschlag: ${esc(c.reply || c.reason || "–")}</small></span><small>${esc(c.action)}</small></div>`).join("") || `<p class="note">Keine offenen Kommentare.</p>`}</div>
    <p class="note">Freigeben geht im Moment im Kanal-Studio; in der nächsten Ausbaustufe direkt hier bei Tom.</p>`;
  wireClose(); openPanel();
}
function renderSettings(msg) {
  view = { type:"settings" };
  panel.innerHTML = head("Einstellungen", inApp() ? "Programm" : "Browser-Vorschau – nur lesend") +
    `<div class="sec"><h3>GitHub-Schlüssel</h3><p class="note">${hasToken ? "Hinterlegt ✓ (sicher in der Windows-Anmeldeinformationsverwaltung)." : "Derselbe Schlüssel wie bei cron-job.org (beginnt mit github_pat_). Nötig, um Aufträge zu starten."}</p>
     <div class="field"><input id="tok" type="password" autocomplete="off" placeholder="github_pat_…"><span style="display:flex;gap:8px"><button class="btn main" id="tok-save">Speichern</button>${hasToken ? `<button class="btn" id="tok-del">Entfernen</button>` : ""}</span></div>
     ${msg ? `<p class="msg ${msg.ok ? "ok" : "err"}">${esc(msg.text)}</p>` : ""}</div>
     <div class="sec"><h3>Datenschutz</h3><p class="note">Aufgaben und Verlauf liegen nur auf diesem PC. Die Zentrale liest Live-Daten von GitHub und deinem Kanal-Studio und startet Abläufe nur auf deinen Klick.</p></div>`;
  wireClose();
  panel.querySelector("#tok-save").addEventListener("click", async () => {
    const r = await bridge.setToken(panel.querySelector("#tok").value);
    if (r.ok) { hasToken = true; renderSettings({ ok:true, text:"Gespeichert." }); } else renderSettings({ ok:false, text:r.msg });
  });
  const del = panel.querySelector("#tok-del"); if (del) del.addEventListener("click", async () => { await bridge.clearToken(); hasToken = false; renderSettings({ ok:true, text:"Entfernt." }); });
  openPanel();
}
document.getElementById("btn-tasks").addEventListener("click", renderTasks);
document.getElementById("btn-comments").addEventListener("click", renderComments);
document.getElementById("btn-settings").addEventListener("click", () => renderSettings());

/* ------------------------------------------------------------ Interaktion 3D */
const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
let hover = null, focus = null, camGoal = null, tgtGoal = null, downAt = null;
function pick(ev) {
  const r = canvas.getBoundingClientRect();
  mouse.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(mouse, camera);
  const hit = ray.intersectObjects(pickables.filter(o => !(focus && o.userData.id === focus)))[0];
  return hit ? hit.object.userData.id : null;
}
canvas.addEventListener("pointermove", ev => { const id = pick(ev); if (id !== hover) { hover = id; canvas.style.cursor = id ? "pointer" : "grab"; } });
canvas.addEventListener("pointerdown", ev => { downAt = [ev.clientX, ev.clientY]; });
canvas.addEventListener("pointerup", ev => {
  if (!downAt || Math.hypot(ev.clientX - downAt[0], ev.clientY - downAt[1]) > 6) return;
  const id = pick(ev); if (id) openDept(id); else if (!focus) closeAll();
});
addEventListener("keydown", e => { if (e.key === "Escape") closeAll(); });

function resize() {
  renderer.setSize(innerWidth, innerHeight, false); camera.aspect = innerWidth / innerHeight;
  camera.fov = innerWidth < 640 ? 50 : 38; camera.updateProjectionMatrix();
}
addEventListener("resize", resize); resize();
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const tmp = new THREE.Vector3(), clock = new THREE.Clock();
function place(el, v) {
  tmp.copy(v).project(camera);
  el.style.left = ((tmp.x + 1) / 2 * innerWidth) + "px"; el.style.top = ((1 - tmp.y) / 2 * innerHeight) + "px";
  return tmp.z < 1;
}
function frame() {
  const t = clock.getElapsedTime();
  if (camGoal) { camera.position.lerp(camGoal, .07); controls.target.lerp(tgtGoal, .07); if (camera.position.distanceTo(camGoal) < .05) camGoal = null; }
  controls.update();
  if (!reduce) {
    if (byId.engine && byId.engine.gear) byId.engine.gear.rotation.z = t * (runs.some(r => r.status !== "completed") ? 3 : .6);
    if (byId.media && byId.media.beacon) byId.media.beacon.material.color.setHSL(0, 1, .45 + .25 * Math.sin(t * 4));
    flies.rotation.y = t * .02;
  }
  DEPTS.forEach(d => {
    const goal = focus === d.id ? 1 : 0;
    d.open += (goal - d.open) * (reduce ? 1 : .1);
    d.roofMesh.position.y = d.h + .17 + d.open * 2.4; d.roofMat.opacity = 1 - d.open;
    d.shell.opacity = 1 - d.open * .88; d.shell.depthWrite = d.open < .5;
    d.roofMesh.visible = d.open < .98; d.inside.visible = d.open > .02;
    (d.extra || []).forEach(m => { m.visible = d.open < .5; });
    const busyAny = d.workers.some(w => w.state === "arbeitet");
    const glow = d.id === hover || d.id === focus ? 1.25 : busyAny ? 1.05 : (d.state === "plan" ? .25 : .8);
    d.shell.emissiveIntensity += (glow - d.shell.emissiveIntensity) * .12;
    d.label.style.display = place(d.label, d.top) && d.open < .5 ? "" : "none";
    d.workers.forEach((w, i) => {
      const busy = w.state === "arbeitet" || w.state === "startet";
      if (!reduce) {
        w.mesh.userData.head.position.y = .93 + (busy ? Math.abs(Math.sin(t * 8 + i)) * .04 : Math.sin(t * 1.5 + i) * .01);
        w.mesh.userData.body.rotation.z = busy ? Math.sin(t * 10 + i) * .05 : 0;
      }
      w.scr.color.setHex(busy ? (Math.sin(t * 6 + i) > 0 ? 0x6cc4ff : 0x3a8fd0) : w.state === "fertig" ? 0x5fd89a : w.state === "Fehler" ? 0xff6b6b : 0x2c6b9e);
      const show = d.open > .8; w.tag.hidden = !show;
      if (show) {
        w.mesh.getWorldPosition(w.anchor); w.anchor.y += 1.3; place(w.tag, w.anchor);
        w.tag.className = "wtag" + (busy ? " busy" : "") + (focus === d.id && sel === i ? " sel" : "");
        w.tag.innerHTML = `${esc(w.name)} <em>${busy ? (w.state === "startet" ? "startet" : Math.round(w.progress) + " %") : esc(w.state === "frei" ? w.role : w.state)}</em>`;
      }
    });
  });
  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}

/* ------------------------------------------------------------ Start */
async function start() {
  const cat = await bridge.catalog();
  hasToken = !!cat.has_token;
  DEPTS = cat.depts;
  DEPTS.forEach(d => buildDept(d));
  DEPTS.forEach(d => {
    const b = document.createElement("button");
    b.className = "tag"; b.innerHTML = `<i class="${d.state === "live" ? "" : d.state}"></i>${esc(d.name)}`;
    b.setAttribute("aria-label", d.name + " öffnen"); b.addEventListener("click", () => openDept(d.id));
    labels.appendChild(b); d.label = b;
    d.workers.forEach((wk, i) => {
      const t = document.createElement("button"); t.className = "wtag"; t.hidden = true;
      t.addEventListener("click", () => selectWorker(d.id, i)); labels.appendChild(t); wk.tag = t;
    });
  });
  document.getElementById("mode").textContent = inApp() ? (hasToken ? "verbunden · Aufträge aktiv" : "verbunden · nur lesend (Schlüssel fehlt)") : "Browser-Vorschau · nur lesend";
  tasks = await bridge.tasks();
  frame();
  await Promise.all([loadRuns(), loadStatus()]);
  setInterval(loadRuns, 30000); setInterval(loadStatus, 300000);
  setInterval(() => { refreshWorkers(); if (view && view.type === "dept" && !pending) { const b = panel.querySelector(".worker.sel .bar i"); if (b) b.style.width = byId[view.id].workers[sel].progress + "%"; } }, 5000);
}
if (inApp()) start(); else if (window.pywebview !== undefined) addEventListener("pywebviewready", start); else {
  let started = false; addEventListener("pywebviewready", () => { if (!started) { started = true; start(); } });
  setTimeout(() => { if (!started) { started = true; start(); } }, 400);
}
