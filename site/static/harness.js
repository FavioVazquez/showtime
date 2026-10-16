/* The harness manual's script (harness/index.html): the topology, the finder, the day replay and the other
   interactive sections, then the starter kit's copy buttons and the loops that play in view. */
(() => {
"use strict";
const TOP = 65;   /* the site header: 64 px + its 1 px rule */
const $ = (s, r = document) => r.querySelector(s);
const NS = "http://www.w3.org/2000/svg";
const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
let reduced = mq.matches;
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
/* #N in rendered text: a link to that issue or PR on the public repo (every number on this page is one of its) */
const PUBLIC_N = new Set([8,14,22,24,27,28,29,33,34,35,36,38,39,40,41,42,43,44,45,46,47,48,50]);
const links = h => String(h).replace(/(^|[^&\w])#(\d{1,3})\b/g, (m, p, n) => PUBLIC_N.has(+n) ? `${p}<a href="https://github.com/FavioVazquez/showtime/issues/${n}">#${n}</a>` : m);
function S(tag, attrs, parent) {
  const e = document.createElementNS(NS, tag);
  for (const k in attrs || {}) e.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(e);
  return e;
}

/* ---------------- theme ---------------- */
const themeBtn = $("#themeBtn");   /* the site header's theme button drives data-theme; this one is optional */
function currentTheme() {
  const a = document.documentElement.getAttribute("data-theme");
  if (a) return a;
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}
function labelTheme() { if (themeBtn) themeBtn.textContent = currentTheme() === "dark" ? "Light" : "Dark"; }
if (themeBtn) themeBtn.addEventListener("click", () => {
  document.documentElement.setAttribute("data-theme", currentTheme() === "dark" ? "light" : "dark");
  labelTheme();
});
labelTheme();

/* ================= 00 TOPOLOGY ================= */
const NODES = {
  favio:    {label:"Favio", sub:"owner · the yes", k:"amber", model:"Human",
             role:"Approves every merge, spend and public word, judges the films, and decides what goes out, in his own words.",
             rules:["A yes in chat, each time: merges, spending, public issues, anything public","Relayed approvals do not count","Publishes a film only if it wins his blind vote"],
             rule:"Nothing public without Favio’s yes. He decides what goes out, in his words."},
  director: {label:"Main session", sub:"director · Opus 5.5", k:"amber", model:"Opus 5.5 (Claude Code)",
             role:"The director: it plans, merges after Favio’s yes, runs Mac tests, files public issues through the issue tool and writes state files.",
             rules:["Merges only after Favio’s yes","State goes to STATE.md, OVERNIGHT.md and PLAN.md, so compactions and restarts lose nothing","Public issues pass the issue tool’s safety check"],
             num:["16 PRs","merged into the private working repo on 9 Oct by ~12:35; issues #38–#48 filed"]},
  haiku:    {label:"Haiku 5.5", sub:"Explore · researcher", k:"cyan", model:"Haiku 5.5",
             role:"Lookups, docs, web and browser work for the Explore and researcher agents.",
             rules:["Lookups, docs, web and browser work","Runs the Explore and researcher agents"],
             rule:"The kind of job: when WebFetch is refused, a Nobel lab reads its primary source in a real browser."},
  sonnet:   {label:"Sonnet 5.5", sub:"worker", k:"cyan", model:"Sonnet 5.5",
             role:"The worker: Mac test runs, decided fixes, merges, eval runs.",
             rules:["Mac test runs, decided fixes, merges, eval runs","Mac review: run_all --changed plus the PR’s own suites, compared with main"],
             num:["900 s → 760 s","the kind of Mac run it owns: #24’s test_render timed out on main, passed on the fix"]},
  opus:     {label:"Opus 5.5", sub:"sub-agents", k:"cyan", model:"Opus 5.5",
             role:"Creative and visual work, claims ledgers, hard debugging, film builds.",
             rules:["Film builds and visual work","Claims ledgers: every sentence sourced"],
             rule:"The creative session’s short films build headless with claude -p on Opus, the API key set for that one command."},
  fable:    {label:"Fable 5.1", sub:"reviewer", k:"cyan", model:"Fable 5.1",
             role:"Independent reviewer at decision points, and the advisor before big plans.",
             rules:["Only at decision points","Every use is logged"],
             num:["FIX FIRST ×2","on #24’s fix before it merged: four catches, all fixed"]},
  jev:      {label:"Jev", sub:"TypeSafe · yes/no", k:"cyan", model:"Jev (TypeSafe)",
             role:"Tiny typed yes/no calls over text, used only as suggestions.",
             rules:["Only through one wrapper","A few thousandths of a cent a call"],
             num:["57 / 65","dedup suggestions decided, all right; Favio’s spot check 10/10; $0.02 for the whole evaluation"]},
  crew:     {label:"showtime crew", sub:"plugin · 10 roles", k:"cyan", model:"Plugin agents",
             role:"Critic, researcher, scriptwriter, storyboard artist, motion designer, sound designer, voice director, editor, brand designer, creative director.",
             rules:["Turn caps: scriptwriter 30, storyboard 50, critic 30, motion 60, editor 80, sound 40","#42 raises scriptwriter to 50 and storyboard to 80","A capped agent is resumed, not restarted"],
             num:["3 rounds","of critic review on Inside the Great Wave; 9 should-fixes fixed"]},
  devin:    {label:"Devin cloud", sub:"cloud · 8 cores", k:"cyan", model:"Devin",
             role:"A cloud machine with no GPU, driven from the Mac with a small send script; the Devin CLI runs locally.",
             rules:["Start reviewers last: devin --cloud -c resumes the account’s newest session","One machine for many turns"],
             num:["13 jobs","on one machine on 9 Oct"]},
  cloud:    {label:"Cloud Project", sub:"Claude Code · cloud", k:"cyan", model:"Claude Code cloud (4 CPU)",
             role:"Opens draft PRs on the private working repo with the exact Mac commands in the body.",
             rules:["No keys","Never device access"],
             rule:"Draft PRs only. Each one still takes the first pass, the Mac review and Favio’s yes."},
  creative: {label:"Creative session", sub:"session · short films", k:"cyan", model:"Claude Code session",
             role:"Proposes film topics; Favio picks one in chat; the crew makes the film, and Favio judges it and posts it himself if it goes out.",
             rules:["Approvals only from Favio directly","Makes films; never posts them"],
             num:["53 min","to make its first film (a UV sky map, 8 Oct)"]},
  reviews:  {label:"Review session", sub:"session · first pass", k:"cyan", model:"Claude Code session",
             role:"Runs the shared PR watcher and the first-pass diff review of cloud PRs.",
             rules:["The only session that runs the shared watcher","Never merges"],
             rule:"First pass only. The merge stays with the director, after Favio’s yes."},
  dev:      {label:"Working repo", sub:"private", k:"steel", model:"GitHub, private",
             role:"Draft PRs live here (“Closes FavioVazquez/showtime#N”); merge commits land after Favio’s yes.",
             rules:["GitHub Actions off on private repos","Tests run on the Mac and on Devin"],
             num:["$3.88","of Actions minutes before they were turned off"]},
  pub:      {label:"Public repo", sub:"FavioVazquez/showtime", k:"steel", model:"GitHub, public",
             role:"github.com/FavioVazquez/showtime. Each release is one clean commit, built by a script in a separate publish repo.",
             rules:["The working repo never goes to the public remote","One clean commit per release"],
             rule:"Releases only: one clean commit each, and nothing public without Favio’s yes."}
};
const EDGES = [["creative","favio"],["favio","director"],
  ["director","haiku"],["director","sonnet"],["director","opus"],["director","fable"],["director","jev"],["director","crew"],["director","devin"],
  ["sonnet","dev"],["devin","dev"],["reviews","dev"],["cloud","dev"],["director","dev"],["dev","pub"]];
const ROUTES = [
  {name:"Ship a fix · #24", steps:[
    ["favio","director","A task reaches the director: renders and checks can hang for 10+ minutes (#24)."],
    ["director","devin","Devin runs the Linux check, the flag experiment and the Linux-only flag build."],
    ["devin","dev","The fix sits in a draft PR on the private working repo."],
    ["dev","sonnet","Mac review against main: test_render timed out at 900 s on main and passed in 760 s on the fix."],
    ["sonnet","fable","A decision point. Fable answers FIX FIRST, twice."],
    ["fable","director","Four catches, all fixed."],
    ["director","favio","The director asks for the yes."],
    ["favio","director","Yes, in chat."],
    ["director","dev","Merge commit; the issue tool marks #24 fixed."],
    ["dev","pub","At release: one clean commit on the public repo."]]},
  {name:"A cloud PR", steps:[
    ["cloud","dev","The cloud Project opens a draft PR, exact Mac commands in the body."],
    ["dev","reviews","The review session takes the first pass on the diff. It never merges."],
    ["reviews","sonnet","Mac review: run_all --changed plus the PR’s own suites, compared with main."],
    ["sonnet","director","The results reach the director."],
    ["director","favio","The director asks for the yes."],
    ["favio","director","Yes, in chat."],
    ["director","dev","Merge commit; the issue tool marks the public issue fixed."]]},
  {name:"A short film", steps:[
    ["creative","favio","The creative session proposes film topics; Favio picks one in chat."],
    ["favio","creative","The pick goes back to the creative session."],
    ["creative","opus","A headless claude -p build on Opus: the API key set for that one command, a cost cap, 75 min."],
    ["opus","creative","A card: the film, with every claim next to its source."],
    ["creative","favio","Favio judges the film. If it goes out, he posts it himself, in his words."],
    ["creative","director","The lessons go to the main session."],
    ["director","pub","The main session files them as 0.4.2 issues, with Favio’s yes."]]}
];
const LAYOUTS = {
  wide: {vb:[1040,690], w:150, h:46, cw:150, center:[],
    pos:{creative:[95,190], favio:[95,342], director:[290,342],
         haiku:[510,120], sonnet:[510,190], opus:[510,260], fable:[510,424], jev:[510,494], crew:[510,564], devin:[510,634],
         reviews:[725,130], dev:[940,342], pub:[940,150], cloud:[940,560]},
    over:{}},
  tall: {vb:[400,540], w:150, h:40, cw:170, center:["director","dev"],
    pos:{creative:[103,36], favio:[297,36], director:[200,110],
         haiku:[103,184], sonnet:[297,184], opus:[103,238], fable:[297,238], jev:[103,292], crew:[297,292], devin:[103,346], reviews:[297,346],
         dev:[200,424], cloud:[103,500], pub:[297,500]}, over:{}}
};
function roundPath(pts, r) {
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const [px,py] = pts[i-1], [x,y] = pts[i], [nx,ny] = pts[i+1];
    const l1 = Math.hypot(x-px,y-py), l2 = Math.hypot(nx-x,ny-y);
    if (!l1 || !l2) continue;
    const rr = Math.min(r, l1/2, l2/2);
    const ax = x - (x-px)/l1*rr, ay = y - (y-py)/l1*rr, bx = x + (nx-x)/l2*rr, by = y + (ny-y)/l2*rr;
    d += ` L${ax},${ay} Q${x},${y} ${bx},${by}`;
  }
  const e = pts[pts.length-1];
  return d + ` L${e[0]},${e[1]}`;
}
function pathFor(L, a, b) {
  const key = a + ">" + b;
  if (L.over[key]) return L.over[key];
  const P = L.pos, [ax,ay] = P[a], [bx,by] = P[b];
  const hh = L.h/2, wa = (L.center.includes(a)?L.cw:L.w)/2, wb = (L.center.includes(b)?L.cw:L.w)/2;
  if (L === LAYOUTS.tall) {
    const Sx = 200, side = x => x < Sx-10 ? "L" : x > Sx+10 ? "R" : "C";
    const sa = side(ax), sb = side(bx);
    const ex = (x,sd,w) => sd === "L" ? x + w : x - w;
    if (sa === "C" && sb === "C") { const s = by > ay ? 1 : -1; return `M${ax},${ay+s*hh} L${bx},${by-s*hh}`; }
    if (sa !== "C" && sb !== "C" && ay === by) return `M${ex(ax,sa,wa)},${ay} L${ex(bx,sb,wb)},${by}`;
    let pts;
    if (sa === "C") { const s = by > ay ? 1 : -1; pts = [[Sx, ay+s*hh],[Sx,by],[ex(bx,sb,wb),by]]; }
    else if (sb === "C") { const s = by > ay ? 1 : -1; pts = [[ex(ax,sa,wa),ay],[Sx,ay],[Sx,by-s*hh]]; }
    else pts = [[ex(ax,sa,wa),ay],[Sx,ay],[Sx,by],[ex(bx,sb,wb),by]];
    return roundPath(pts, 7);
  }
  if (Math.abs(ax-bx) < 40) {
    const between = Object.keys(P).some(k => k!==a && k!==b && Math.abs(P[k][0]-ax) < 40 && P[k][1] > Math.min(ay,by) && P[k][1] < Math.max(ay,by));
    if (!between) { const s = by > ay ? 1 : -1; return `M${ax},${ay+s*hh} L${bx},${by-s*hh}`; }
    const dir = ax > 800 ? -1 : 1, sx = ax + dir*wa, exx = bx + dir*wb, cx = sx + dir*70;
    return `M${sx},${ay} C${cx},${ay} ${cx},${by} ${exx},${by}`;
  }
  const s = bx > ax ? 1 : -1, sx = ax + s*wa, exx = bx - s*wb, mx = (sx+exx)/2;
  return `M${sx},${ay} C${mx},${ay} ${mx},${by} ${exx},${by}`;
}

const svg = $("#topo"), panel = $("#topoPanel"), stage = $("#topoStage");
let L = null, layoutName = "", nodeEls = {}, ambient = [], gRoute, pkt, halo;
let routeIdx = 0, stepIdx = 0, phase = "travel", phaseT = 0, segEls = [], selected = null, playing = !reduced, visible = true;

function render() {
  const name = stage.clientWidth < 800 ? "tall" : "wide";
  if (name === layoutName) return;
  layoutName = name; L = LAYOUTS[name];
  svg.classList.toggle("tall", name === "tall");
  svg.innerHTML = "";
  svg.setAttribute("viewBox", `0 0 ${L.vb[0]} ${L.vb[1]}`);
  const gE = S("g", {}, svg), gA = S("g", {}, svg);
  gRoute = S("g", {}, svg);
  const gN = S("g", {}, svg);
  ambient = [];
  EDGES.forEach(([a,b], i) => {
    const p = S("path", {d: pathFor(L,a,b), class:"edge"}, gE);
    if (!reduced) {
      const c = S("circle", {r: name === "wide" ? 2.4 : 2, class:"amb"}, gA);
      ambient.push({p, c, len: p.getTotalLength(), off: (i*137) % 1000});
    }
  });
  nodeEls = {};
  Object.entries(L.pos).forEach(([id,[x,y]]) => {
    const n = NODES[id], w = L.center.includes(id) ? L.cw : L.w, h = L.h;
    const g = S("g", {class:`node k-${n.k}`, transform:`translate(${x-w/2},${y-h/2})`, tabindex:"0", role:"button",
      "aria-label": `${n.label}, ${n.sub}. Show details.`}, gN);
    S("rect", {class:"box", width:w, height:h}, g);
    S("rect", {class:"bar", width:3, height:h}, g);
    const t1 = S("text", {class:"nl", x:12, y: name === "wide" ? 20 : 18}, g); t1.textContent = n.label;
    const t2 = S("text", {class:"ns", x:12, y: name === "wide" ? 36 : 32}, g); t2.textContent = n.sub;
    g.addEventListener("click", () => select(id));
    g.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(id); } });
    nodeEls[id] = g;
  });
  pkt = null; halo = null;
  if (selected) nodeEls[selected].classList.add("sel");
  buildRoute();
}
function buildRoute() {
  gRoute.innerHTML = "";
  const R = ROUTES[routeIdx];
  segEls = R.steps.map(([a,b]) => {
    const p = S("path", {d: pathFor(L,a,b), class:"route-seg"}, gRoute);
    const len = p.getTotalLength();
    p.style.strokeDasharray = len; p.style.strokeDashoffset = reduced ? 0 : len;
    return {p, len};
  });
  if (!reduced) {
    halo = S("circle", {r: 9, class:"pkt-halo"}, gRoute);
    pkt = S("circle", {r: 4.2, class:"pkt"}, gRoute);
  }
  applyStep();
}
function applyStep() {
  const R = ROUTES[routeIdx];
  Object.values(nodeEls).forEach(g => g.classList.remove("hot"));
  segEls.forEach((s,i) => {
    if (reduced) return;
    s.p.classList.toggle("done", i < stepIdx);
    s.p.style.strokeDashoffset = i < stepIdx ? 0 : s.len;
    s.p.style.opacity = i <= stepIdx ? "" : "0";
  });
  const st = R.steps[stepIdx];
  if (st) {
    $("#tickK").textContent = `${String(stepIdx+1).padStart(2,"0")} / ${String(R.steps.length).padStart(2,"0")}`;
    $("#tickT").textContent = st[2];
    if (!reduced) nodeEls[st[0]] && nodeEls[st[0]].classList.add("hot");
  }
  if (!selected) {
    const items = panel.querySelectorAll("ol li");
    if (panel.dataset.route === String(routeIdx) && items.length) items.forEach((li,i) => { if (!reduced && i === stepIdx) li.setAttribute("aria-current","step"); else li.removeAttribute("aria-current"); });
    else panelRoute();
  }
}
function panelRoute() {
  panel.dataset.route = String(routeIdx);
  const R = ROUTES[routeIdx];
  panel.innerHTML = `<div class="sub">${reduced ? "Route" : "Now running"}</div><h3>${esc(R.name)}</h3>
    <p>Select any box in the diagram for its role, rules and one number from the log.</p>
    <ol>${R.steps.map((s,i) => `<li${(!reduced && i === stepIdx) ? ' aria-current="step"' : ""}><b style="font-weight:600;color:inherit">${esc(NODES[s[0]].label)} → ${esc(NODES[s[1]].label)}.</b> ${esc(s[2])}</li>`).join("")}</ol>`;
}
function select(id) {
  if (selected && nodeEls[selected]) nodeEls[selected].classList.remove("sel");
  selected = id;
  nodeEls[id].classList.add("sel");
  const n = NODES[id];
  panel.dataset.route = "";
  $("#topoLive").textContent = `Details: ${n.label}`;
  if (window.matchMedia("(max-width:1179px)").matches) panel.scrollIntoView({block:"nearest", behavior: reduced ? "auto" : "smooth"});
  const big = n.num ? `<div class="bignum"><b>${esc(n.num[0])}</b><span>${links(esc(n.num[1]))}</span></div>`
                    : `<div class="bignum rule"><b>Rule</b><span>${esc(n.rule)}</span></div>`;
  panel.innerHTML = `<button class="btn ghost closebtn" type="button" id="pClose" aria-label="Close details">Close</button>
    <div class="sub">${esc(n.sub)}</div><h3>${esc(n.label)}</h3>
    <dl class="kv"><dt>Model</dt><dd>${esc(n.model)}</dd></dl>
    <p>${links(esc(n.role))}</p>
    <ul>${n.rules.map(r => `<li>${links(esc(r))}</li>`).join("")}</ul>${big}`;
  $("#pClose").addEventListener("click", () => { const back = selected; deselect(); if (back && nodeEls[back]) nodeEls[back].focus(); });
}
function deselect() {
  if (selected && nodeEls[selected]) nodeEls[selected].classList.remove("sel");
  selected = null; panelRoute();
}
document.addEventListener("keydown", e => { if (e.key === "Escape" && selected) { const back = selected; deselect(); if (nodeEls[back]) nodeEls[back].focus(); } });

const routeBtns = $("#routeBtns");
ROUTES.forEach((R,i) => {
  const b = document.createElement("button");
  b.className = "btn"; b.type = "button"; b.textContent = R.name; b.setAttribute("aria-pressed", i === 0 ? "true" : "false");
  b.addEventListener("click", () => {
    routeIdx = i; stepIdx = 0; phase = "travel"; phaseT = 0;
    [...routeBtns.children].forEach((c,j) => c.setAttribute("aria-pressed", j === i ? "true" : "false"));
    buildRoute();
  });
  routeBtns.appendChild(b);
});
const playBtn = $("#playBtn");
function setPlaying(v) {
  playing = v && !reduced;
  playBtn.textContent = playing ? "Pause" : "Play";
  playBtn.setAttribute("aria-label", playing ? "Pause the animation" : "Play the animation");
  playBtn.hidden = reduced;
}
playBtn.addEventListener("click", () => setPlaying(!playing));
setPlaying(playing);

const ease = t => t < .5 ? 2*t*t : 1 - Math.pow(-2*t+2, 2)/2;
let last = performance.now(), clock = 0;
function frame(now) {
  const dt = Math.min(.05, (now - last)/1000); last = now;
  if (playing && visible && !reduced) {
    clock += dt;
    ambient.forEach(a => {
      const d = ((clock*34 + a.off) % (a.len + 40)) - 20;
      if (d < 0 || d > a.len) { a.c.setAttribute("opacity", 0); return; }
      const pt = a.p.getPointAtLength(d);
      a.c.setAttribute("cx", pt.x); a.c.setAttribute("cy", pt.y); a.c.setAttribute("opacity", "");
    });
    const R = ROUTES[routeIdx], seg = segEls[stepIdx];
    phaseT += dt;
    if (phase === "travel" && seg) {
      const dur = Math.max(.8, Math.min(1.9, seg.len / 240));
      const p = Math.min(1, phaseT/dur), e = ease(p);
      seg.p.style.opacity = "";
      seg.p.style.strokeDashoffset = seg.len * (1 - e);
      const pt = seg.p.getPointAtLength(seg.len * e);
      pkt.setAttribute("cx", pt.x); pkt.setAttribute("cy", pt.y);
      halo.setAttribute("cx", pt.x); halo.setAttribute("cy", pt.y);
      pkt.setAttribute("opacity", 1); halo.setAttribute("opacity", 1);
      if (p >= 1) { phase = "dwell"; phaseT = 0; const tgt = nodeEls[R.steps[stepIdx][1]]; if (tgt) tgt.classList.add("hot"); }
    } else if (phase === "dwell" && phaseT > 1.25) {
      stepIdx++; phaseT = 0;
      if (stepIdx >= R.steps.length) { phase = "gap"; stepIdx = R.steps.length - 1; pkt.setAttribute("opacity", 0); halo.setAttribute("opacity", 0); }
      else { phase = "travel"; applyStep(); }
    } else if (phase === "gap" && phaseT > 2.2) {
      routeIdx = (routeIdx + 1) % ROUTES.length; stepIdx = 0; phase = "travel"; phaseT = 0;
      [...routeBtns.children].forEach((c,j) => c.setAttribute("aria-pressed", j === routeIdx ? "true" : "false"));
      buildRoute();
    }
  }
  requestAnimationFrame(frame);
}
if ("IntersectionObserver" in window) {
  new IntersectionObserver(es => { visible = es[0].isIntersecting; }).observe(stage);
}
document.addEventListener("visibilitychange", () => { if (document.hidden) visible = false; else visible = true; });
render();
requestAnimationFrame(frame);
let rT; window.addEventListener("resize", () => { clearTimeout(rT); rT = setTimeout(render, 120); });
mq.addEventListener && mq.addEventListener("change", e => { reduced = e.matches; layoutName = ""; setPlaying(!reduced); render(); });

document.querySelectorAll(".sec-head").forEach(h => { const n = h.querySelector(".sec-no"); if (!n) return; const g = document.createElement("span"); g.className = "snum"; g.setAttribute("aria-hidden","true"); g.textContent = n.textContent.trim().split(/\s/)[0].slice(0,3); h.prepend(g); });
if (reduced) ["#raceBtn"].forEach(q => { const b = $(q); if (b) b.hidden = true; });

/* ================= 01 TIMELINE ================= */
(function timeline() {
  const DAYS = ["28","29","30","1","2","3","4","5","6","7","8","9","10","11","12","13","14","15","16"], ND = DAYS.length;
  const REL = [
    {v:"0.1.0", d:"28 Sep", day:0, t:"Public. “Your agent directs. Your machine renders.”"},
    {v:"0.2.0", d:"29 Sep", day:1, t:"Works in every coding agent; lazy downloads."},
    {v:"0.3.0", d:"30 Sep", day:2, t:"Quality-first default: a critic on every video; “lean” is opt-in."},
    {v:"0.3.1–0.3.5", d:"30 Sep – 3 Oct", day:2, end:5, t:"Patch releases 0.3.1 through 0.3.5."},
    {v:"0.4.0", d:"5 Oct", day:7, t:"Questions built in, a first-viewer story check, pr-video, a hearing pass."},
    {v:"0.4.1", d:"8 Oct", day:10, t:"Speed, looks, talking-head cards, a new showreel."},
    {v:"0.4.2", d:"11 Oct", day:13, t:"Shipped once every check was green on all four systems; 16 PRs had merged on 9 Oct alone."},
    {v:"0.4.3", d:"13 Oct", day:14.8, t:"Living diagrams; recap and repro turn a coding session or a failing test into a short narrated film."},
    {v:"0.4.4", d:"13 Oct", day:15.3, t:"X-ray: a real clip’s inside, drawn in sync with its sound and checked with a receipt."},
    {v:"0.4.5", d:"15 Oct", day:17, t:"X-ray from data, and the skill reorganized by family with a routing eval."},
    {v:"0.4.6", d:"16 Oct", day:18, t:"check catches text over text, text outside a phone’s free area, and a stuck page."}
  ];
  const CTX = [
    {k:"A", d:"2 Oct", day:4, t:"Comparison rounds on Devin begin. Plain Opus won rounds 1 and 5, so showtime’s reel was not published."},
    {k:"B", d:"5 Oct", day:7, t:"Round 6, after a density fix: showtime 1st and 2nd, the plain winner 3rd."},
    {k:"C", d:"8 Oct", day:10, t:"Venues measured (Phase 0). The creative session’s first film. Jev evaluated for $0.02."},
    {k:"D", d:"10–11 Oct", day:12, end:13, t:"The release waits until every check is green on all four systems, Intel included."},
    {k:"E", d:"12 Oct", day:14, t:"Edition 1 of this manual goes public with the first article. Edition 2 follows with 0.4.6."}
  ];
  const pct = d => (d + .5) / ND * 100;
  const root = $("#timeline");
  let axis = `<div class="tl-axis" aria-hidden="true"><div class="tl-days">${DAYS.map((d,i) => `<span class="${i===0||i===3?"m":""}">${d}${i===0?" Sep":i===3?" Oct":""}</span>`).join("")}</div>`;
  REL.forEach(r => {
    if (r.end != null) axis += `<div class="tl-range" style="left:${pct(r.day)}%;width:${pct(r.end)-pct(r.day)}%"></div>`;
    else axis += `<div class="tl-mk${r.wip?" wip":""}" style="left:${pct(r.day)}%"></div>`;
  });
  CTX.forEach(c => {
    const x = c.end != null ? (pct(c.day)+pct(c.end))/2 : pct(c.day);
    if (c.end != null) axis += `<div class="tl-ctxr" style="left:${pct(c.day)}%;width:${pct(c.end)-pct(c.day)}%"></div>`;
    axis += `<div class="tl-ctx" style="left:${x}%;">${c.k}</div>`;
  });
  axis += `</div>`;
  let lead = `<svg class="tl-lead" viewBox="0 0 100 46" preserveAspectRatio="none" aria-hidden="true">`;
  REL.forEach((r,i) => {
    const x0 = r.end != null ? (pct(r.day)+pct(r.end))/2 : pct(r.day), x1 = (i + .5)/REL.length*100;
    lead += `<path d="M${x0},0 L${x0},14 L${x1},34 L${x1},46"/>`;
  });
  lead += `</svg>`;
  const cards = `<ol class="tl-cards" style="list-style:none;margin:0;padding:0;--n:${REL.length}">${REL.map(r => `<li class="tl-card${r.wip?" wip":""}"><div class="v">${r.v}</div><div class="d">${r.d}</div><p>${esc(r.t)}</p></li>`).join("")}</ol>`;
  const around = `<div class="subh" style="margin-top:28px">Around the releases</div><div class="tl-around">${CTX.map(c => `<div><b>${c.k}</b><i>${c.d}</i><br>${esc(c.t)}</div>`).join("")}</div>`;
  root.innerHTML = axis + lead + cards + around;
})();

/* chips and model colours, shared by the day replay */
const modelCls = m => { const s = String(m || "").toLowerCase();
  return /fable/.test(s) ? "m-fable" : /opus/.test(s) ? "m-opus" : /haiku/.test(s) ? "m-haiku" : /sonnet/.test(s) ? "m-sonnet" : /favio|owner|human/.test(s) ? "m-human" : ""; };
const chip = (txt, cls) => txt ? `<span class="chip ${cls || ""}"><i></i>${esc(txt)}</span>` : "";
const arr = v => Array.isArray(v) ? v : [];

/* ================= 03 A DAY IN THE HARNESS (replay) ================= */
/* 9 Oct 2026, from the day log. Times are the log's own; "~" where the log says so; ""
   where the log keeps the order but gives no time ("between" names the window the log
   does give). Public edition: private PR numbers, repo names and tools are generalized. */
const DAY_0909 = {date:"2026-10-09", title:"9 Oct: 16 merges, the render stall closed, the Great Wave goes public",
 events:[
  {t:"~01:00", lane:"opus", model:"Opus 5.5", what:"Great Wave final polish: an Opus director with two critics, a sound designer and three look reviewers; the Fable advisor planned before the build and before done"},
  {t:"~01:25", lane:"owner", model:"Favio", gate:"merge", what:"A one-night rule: merge what passes the Mac review tonight"},
  {t:"01:35", lane:"main", model:"Opus 5.5", gate:"merge", what:"Merges extra voice engines (closes #8)"},
  {t:"01:50", lane:"owner", model:"Favio", what:"Relays two new PRs: eval graders with three new eval cases, and a tools PR for the creative session"},
  {t:"01:50", lane:"main", model:"Opus 5.5", what:"The sound-designer PR gets FIX FIRST; the message goes to Favio, still awake, to send to the cloud Project"},
  {t:"", between:["01:50","03:53"], lane:"owner", model:"Favio", gate:"spend", what:"Yes: run the grader evals under a cost cap and merge only if scores hold; merge the creative session’s PR if its Mac tests pass"},
  {t:"", between:["01:50","03:53"], lane:"sonnet", model:"Sonnet 5.5", what:"Mac reviews start: the grader evals, and the creative session’s PR"},
  {t:"", between:["01:50","03:53"], lane:"main", model:"Opus 5.5", gate:"merge", what:"Merges the creative session’s PR (+46 tests): 171 OK with correct time-zone data"},
  {t:"", between:["01:50","03:53"], lane:"devin", model:"Devin", what:"Full suite on Devin cloud: 81 of 82 files pass in 16.0 min on 8 cores; setup --full took 55 min"},
  {t:"", between:["01:50","03:53"], lane:"main", model:"Opus 5.5", what:"Builds a small send script: follow-ups go to the same Devin cloud session"},
  {t:"", between:["01:50","03:53"], lane:"main", model:"Opus 5.5", gate:"merge", what:"Merges the --fit estimate: within 1–3 words of the measured cut (closes #28)"},
  {t:"", between:["01:50","03:53"], lane:"main", model:"Opus 5.5", gate:"merge", what:"Merges a test fix: a suite now skips without LaTeX (Devin’s fix)"},
  {t:"", between:["01:50","03:53"], lane:"sonnet", model:"Sonnet 5.5", what:"Grader eval: FIX FIRST, inside its cost cap"},
  {t:"", between:["01:50","03:53"], lane:"devin", model:"Devin", what:"Linux check of #24: ship, 83/83, but 9.3% slower; the branch dropped --disable-frame-rate-limit"},
  {t:"", between:["01:50","03:53"], lane:"sonnet", model:"Sonnet 5.5", what:"Mac control runs: test_render times out at 900 s on main and passes in 760 s on the fix"},
  {t:"", between:["01:50","03:53"], lane:"main", model:"Opus 5.5", gate:"merge", what:"Merges “full crew” (closes #33)"},
  {t:"", between:["01:50","03:53"], lane:"devin", model:"Devin", what:"Flag experiment: with the flag back, 5% faster than main and 4 stall tests pass; recommends Linux only"},
  {t:"", between:["01:50","03:53"], lane:"devin", model:"Devin", what:"Connection drops mid-turn; the same session resumes and picks up where it was"},
  {t:"", between:["01:50","03:53"], lane:"main", model:"Opus 5.5", gate:"merge", what:"Merges audio mix validation (closes #27)"},
  {t:"", between:["01:50","03:53"], lane:"main", model:"Opus 5.5", what:"Main’s scoreboard test expected 14 eval cases; the “full crew” PR added a 15th. Fixed on main"},
  {t:"", between:["01:50","03:53"], lane:"devin", model:"Devin", what:"#29 splice done: a draft PR"},
  {t:"03:53", lane:"main", model:"Opus 5.5", what:"Log checkpoint: every entry above happened before 03:53, in this order"},
  {t:"", between:["03:53","07:20"], lane:"devin", model:"Devin", what:"Connection drops again; the send script now resumes the same session by itself (5 tries)"},
  {t:"", between:["03:53","07:20"], lane:"devin", model:"Devin", what:"Setup fixes pushed: retry a broken extra, preflight build headers, 83/83. A draft PR"},
  {t:"", between:["03:53","07:20"], lane:"devin", model:"Devin", what:"Measurements for chapter mode (#22)"},
  {t:"", between:["03:53","07:20"], lane:"main", model:"Opus 5.5", what:"macOS flag check: the flag breaks the stall guard on macOS for +22% CPU. A draft PR keeps it Linux-only"},
  {t:"", between:["03:53","07:20"], lane:"fable", model:"Fable 5.1", what:"Reviews the stall fix: FIX FIRST (a CHANGELOG entry in the wrong release, an unbacked “0.4 of a core”, a false-fire risk). All fixed in one commit"},
  {t:"", between:["03:53","07:20"], lane:"main", model:"Opus 5.5", gate:"merge", what:"Merges the sound designer (closes #34)"},
  {t:"", between:["03:53","07:20"], lane:"sonnet", model:"Sonnet 5.5", what:"Footage eval case with a new grader: with 3/3, without 3/3. Prompt-only takes don’t discriminate"},
  {t:"", between:["03:53","07:20"], lane:"devin", model:"Devin", what:"Chapter-mode data: no speed from chapters on 8 cores; auto picked 3 workers where 8 were 33% faster"},
  {t:"07:20", lane:"owner", model:"Favio", gate:"merge", what:"Standing yeses, by name: the stall fix after a Fable re-check and a clean Mac review; the splice and setup PRs when their Mac reviews are clean"},
  {t:"", between:["07:20","~11:20"], lane:"devin", model:"Devin", what:"Auto workers: 3 on 8 threads is by design. The join bug is real: edit render drops the AAC priming twice, audio 21 ms early"},
  {t:"", between:["07:20","~11:20"], lane:"fable", model:"Fable 5.1", what:"Re-checks the stall fix: fixes resolved; one new wrong figure, a 5% that should be about 10%, fixed"},
  {t:"", between:["07:20","~11:20"], lane:"sonnet", model:"Sonnet 5.5", what:"Scaffolded footage case: with 3/3, without 0/3, so it discriminates"},
  {t:"", between:["07:20","~11:20"], lane:"main", model:"Opus 5.5", gate:"merge", what:"Merges the eval graders (closes #35), with Favio’s OK"},
  {t:"", between:["07:20","~11:20"], lane:"main", model:"Opus 5.5", what:"Inside the Great Wave final delivered: qa warns only on the loop seam; −14.1 LUFS"},
  {t:"", between:["07:20","~11:20"], lane:"devin", model:"Devin", what:"Join fix: a draft PR. A film lab’s data toys pushed; an independent toy review starts in a separate Devin session"},
  {t:"", between:["07:20","~11:20"], lane:"devin", model:"Devin", what:"Toys fixed, but by the reviewer session, so not independently; Fable’s claims review becomes the final check"},
  {t:"", between:["07:20","~11:20"], lane:"main", model:"Opus 5.5", gate:"merge", what:"Merges the render-stall fix (closes #24), on Favio’s rule: a clean Mac review plus Fable’s fixes"},
  {t:"", between:["07:20","~11:20"], lane:"main", model:"Opus 5.5", gate:"public", what:"Files #38, #39, #40 and #41 through the issue tool; adds the chapter-mode data to #22"},
  {t:"", between:["07:20","~11:20"], lane:"owner", model:"Favio", what:"Sends the cloud Project its morning queue: the guard test, load flakes, a draft PR for #41, the #29 analysis"},
  {t:"", between:["07:20","~11:20"], lane:"main", model:"Opus 5.5", gate:"merge", what:"Merges the 9:16 splice (closes #29) after a table conflict with the stall fix; files #43"},
  {t:"", between:["07:20","~11:20"], lane:"owner", model:"Favio", gate:"public", what:"Favio posts Inside the Great Wave on X, LinkedIn and Instagram Reels"},
  {t:"", between:["07:20","~11:15"], lane:"main", model:"Opus 5.5", gate:"merge", what:"Merges the setup fixes (closes #39, #40)"},
  {t:"", between:["","~11:00"], lane:"owner", model:"Favio", what:"Picks a topic for the creative session’s next short film"},
  {t:"", between:["","~11:00"], lane:"creative", model:"Opus 5.5 (headless)", what:"The film starts blind: --disallowedTools swallowed the prompt. Option first, a regression test, relaunch"},
  {t:"", between:["","~11:00"], lane:"main", model:"Opus 5.5", what:"Harness manual v2 goes to Favio"},
  {t:"~11:15", lane:"main", model:"Opus 5.5", what:"State written to STATE.md before a compact, so nothing is lost"},
  {t:"~11:20", lane:"main", model:"Opus 5.5", gate:"merge", what:"Merges crew turn caps (closes #42), a guard test for #24 and load-flake fixes, with Favio’s yes"},
  {t:"~11:20", lane:"main", model:"Opus 5.5", gate:"public", what:"Files five issues from the creative session’s lessons, #44–#48, on the public repo"},
  {t:"~11:45", lane:"owner", model:"Favio", gate:"public", what:"Public PR #36 duplicated the voice-engine work already merged: not merged, with credit, on Favio’s yes"},
  {t:"~12:05", lane:"main", model:"Opus 5.5", gate:"merge", what:"Merges a CHANGELOG credit for #8 and the edit-render audio sync (closes #38; standing yes)"},
  {t:"", lane:"main", model:"Opus 5.5", gate:"merge", what:"Merges auto workers (closes #41)"},
  {t:"~13:55", lane:"owner", model:"Favio", what:"Yes to the next lab’s prep, this manual’s v3, and 0.4.2 = everything"},
  {t:"~13:55", lane:"haiku", model:"Haiku 5.5", what:"The next lab’s pre-research: the first Haiku pass fails on a 403"},
  {t:"~13:55", lane:"sonnet", model:"Sonnet 5.5", what:"Launched: the pre-research again with curl, and two lane workers on six public issues"},
  {t:"~13:55", lane:"opus", model:"Opus 5.5", what:"Launched: a nightly-CI task, a chapter-mode design note (#22), and this manual’s v3"}
 ]};

/* The release day: 10 Oct afternoon to 11 Oct night, from the day log. Times past
   midnight are written +24 h (e.g. 25:37 = 01:37 on 11 Oct) so the clock runs on. */
const DAY_1011 = {date:"2026-10-11", title:"10–11 Oct: 0.4.2 waits for green, then ships", dayNames:["10 Oct","11 Oct"],
 events:[
  {t:"~14:45", lane:"main", model:"Opus 5.5", gate:"merge", what:"Merges the last docs PR: 0.4.2 is fully merged on the working repo"},
  {t:"", between:["~14:45","15:15"], lane:"fable", model:"Fable 5.1", what:"Fable reads the whole wave as one release: FIX FIRST, no code blocker. Six release-record fixes: duplicated CHANGELOG entries, PRs without one, a private name in a test fixture, a missing What’s new section"},
  {t:"15:15", lane:"sonnet", model:"Sonnet 5.5", what:"A release-prep PR opens for Fable’s fixes; Devin and the Mac review start"},
  {t:"~15:50", lane:"devin", model:"Devin", what:"Devin reviews release prep: FIX FIRST, no blocker. A speed figure was the 8-worker number, not the default, and What’s new must ship with the version bump"},
  {t:"16:05", lane:"sonnet", model:"Sonnet 5.5", what:"Mac full suite: 82 of 84 files in 89 min; the 2 failures pass alone, on main and on 0.4.1: timing flakes under load"},
  {t:"16:20", lane:"main", model:"Opus 5.5", gate:"merge", what:"Merges release prep: 0.4.2 is complete on the working repo"},
  {t:"~17:55", lane:"owner", model:"Favio", gate:"public", what:"Favio gives the go for the 0.4.2 release; he will publish npm and the MCP Registry himself"},
  {t:"18:05", lane:"sonnet", model:"Sonnet 5.5", what:"The version-bump PR opens; Devin and the Mac review start"},
  {t:"18:25", lane:"devin", model:"Devin", what:"Devin reviews the bump: FIX FIRST, no blocker. A README figure sat next to the wrong default, and two claims were stronger than the CHANGELOG"},
  {t:"18:55", lane:"main", model:"Opus 5.5", gate:"merge", what:"Merges the version bump: both reviews say MERGE on the same head"},
  {t:"", between:["18:30","19:45"], lane:"main", model:"Opus 5.5", gate:"public", what:"The release branch is built in the publish repo and opened as public PR #50; the full test tier on all four systems starts"},
  {t:"", between:["19:10","20:10"], lane:"main", model:"Opus 5.5", what:"Release PR CI: three test-only failures (a chapters test, a capture-size test that assumed a 600 px window, a Windows scaffold script). A fix PR with a guard test opens"},
  {t:"20:35", lane:"owner", model:"Favio", what:"Favio says there is no hurry: the release waits until every check is green, the full tier on Intel included"},
  {t:"", between:["20:10","21:10"], lane:"main", model:"Opus 5.5", gate:"merge", what:"Merges the test fixes; the public release branch is updated and CI runs again"},
  {t:"", between:["22:05","23:05"], lane:"main", model:"Opus 5.5", what:"Full tier: two product issues. check times out reading the page size on slow CPU-only runners (the root of #14), and the chapter-mode seam check fails on Windows. One Opus agent on each"},
  {t:"~23:20", lane:"opus", model:"Opus 5.5", what:"The Windows join race: the seam check compared a frame after the output had finished, and Windows often lost the race. Fix: both inputs at t=0, and a test that reproduces it"},
  {t:"23:35", lane:"devin", model:"Devin", what:"Devin reviews the join fix: MERGE, five nits; Favio wants all five fixed"},
  {t:"~24:00", lane:"opus", model:"Opus 5.5", what:"#14’s root cause: the size read before a clipped screenshot waited on a software-rendered WebGL frame under a flat 60 s. It now sits under the render-stall guard, with a new test"},
  {t:"", between:["00:05","01:05"], lane:"main", model:"Opus 5.5", gate:"merge", what:"Merges the join fix: both reviews say MERGE"},
  {t:"24:40", lane:"devin", model:"Devin", what:"Devin reviews the #14 fix: FIX FIRST. A page that never loads would hang for 10 minutes instead of failing in about a minute (reproduced)"},
  {t:"25:37", lane:"opus", model:"Opus 5.5", what:"Fixes pushed: a bounded page load, findings kept on second pages, one shared 10-minute budget"},
  {t:"", between:["02:20","03:35"], lane:"main", model:"Opus 5.5", gate:"merge", what:"Merges the #14 fix; the public issue gets a corrected note through the issue tool"},
  {t:"", between:["02:30","07:30"], lane:"main", model:"Opus 5.5", what:"The public release branch is updated and the final full tier starts. Release only if all green"},
  {t:"", between:["06:50","07:50"], lane:"main", model:"Opus 5.5", what:"Final full tier: PR checks, Linux and Windows green. A macOS flake, and the Intel showreel test hits its 300 s limit: slow now, no longer an error"},
  {t:"31:30", lane:"devin", model:"Devin", what:"Devin reviews the test PR: FIX FIRST. run_all’s 900 s per-file default would stop the showreel test on macOS runners. Fixed: --timeout 2400 in the nightly"},
  {t:"", between:["07:20","08:20"], lane:"main", model:"Opus 5.5", gate:"merge", what:"Merges the timeout fix; the full tier runs again"},
  {t:"", between:["09:30","10:30"], lane:"owner", model:"Favio", what:"Linux and macOS 14 green; three browser-timing flakes on Intel and Windows. Favio chooses: harden all three, then release"},
  {t:"35:12", lane:"opus", model:"Opus 5.5", what:"The flaky-tests PR: each test now waits for what it needs; one CI failure is first reproduced locally, 10 of 10"},
  {t:"36:01", lane:"devin", model:"Devin", what:"Devin: MERGE, but one check was one-sided, and a mutant proved it. Favio wants it fixed"},
  {t:"36:36", lane:"opus", model:"Opus 5.5", what:"Round 2: the check is two-sided; Devin’s mutant now fails 3 of 3"},
  {t:"", between:["13:30","14:30"], lane:"main", model:"Opus 5.5", gate:"merge", what:"Merges the flaky-test fixes; the final full tier runs again"},
  {t:"", between:["15:15","16:15"], lane:"main", model:"Opus 5.5", what:"End-to-end on ARM Linux fails one test: a poster colour at 0.754 against a 0.75 tolerance. The first fix raises the tolerance"},
  {t:"39:51", lane:"sonnet", model:"Sonnet 5.5", what:"The Mac review finds the root cause: ffmpeg’s gradient source was randomly seeded, so every run drew a different picture. Fixed seed; a mutant fails every run"},
  {t:"40:36", lane:"main", model:"Opus 5.5", gate:"merge", what:"Merges the fixed seed. Intel is still running, so the public push waits: a push could cancel it"},
  {t:"", between:["16:40","17:40"], lane:"main", model:"Opus 5.5", what:"Intel is cancelled at its 180-minute cap, at file 77 of 84; the showreel test had failed after 1,167 s, and the details went with the cancel"},
  {t:"", between:["16:40","17:40"], lane:"owner", model:"Favio", what:"Favio chooses: diagnose Intel first. A CI PR raises the cap to 300 minutes"},
  {t:"41:17", lane:"main", model:"Opus 5.5", what:"0.4.3 in the works, on its own branch"},
  {t:"", between:["17:17","~17:40"], lane:"devin", model:"Devin", what:"Devin reviews the CI PR: FIX FIRST. A narrowed manual run could pass as a full run and close the nightly-failing issue by accident. Fixed, with a guard test"},
  {t:"~41:40", lane:"main", model:"Opus 5.5", what:"End-to-end on Windows fails: three parallel audio mixes replace one report file, and Windows refuses while another process holds it. A fix PR: the write retries for 2 s, with a test and a mutant"},
  {t:"~41:40", lane:"main", model:"Opus 5.5", what:"The watchdog was reading a symlink’s age, not its log’s; one flag on stat fixes it"},
  {t:"", between:["17:15","18:15"], lane:"main", model:"Opus 5.5", gate:"merge", what:"Merges the CI PR (both reviews MERGE on the same head); the public release branch is rebuilt"},
  {t:"~41:50", lane:"main", model:"Opus 5.5", what:"The Intel showreel test alone passes: 21 tests in 536 s. The 1,167 s failure came from load, with no product bug behind it. A full Intel tier on the 300-minute cap"},
  {t:"~41:52", lane:"devin", model:"Devin", what:"Devin reviews the Windows fix: MERGE, with two should-fixes: the CHANGELOG blamed the wrong command, and the error must name both paths"},
  {t:"~42:10", lane:"main", model:"Opus 5.5", gate:"merge", what:"Merges the Windows fix after three Devin re-checks: the wording, both paths, a Windows assert"},
  {t:"", between:["18:45","19:45"], lane:"main", model:"Opus 5.5", what:"All PR checks green on the release branch, Windows included. The final full tier starts on all four systems"},
  {t:"~43:20", lane:"main", model:"Opus 5.5", what:"The cancelled Intel run had reached 68 of 84, all passing but one pace test; the final run will show it"},
  {t:"", between:["20:50","22:00"], lane:"main", model:"Opus 5.5", what:"Final full tier green on all four systems, Intel included (1 h 43 min)"},
  {t:"", between:["20:50","22:00"], lane:"owner", model:"Favio", gate:"public", what:"0.4.2 is released on Favio’s go: public PR #50 merged, tag v0.4.2, the GitHub release, What’s new on the site"}
 ]};

/* Edition 2: 15 Oct in UTC, only merges, compactions, checks, reviews and releases, generic lanes; merge and
   compaction times are the PR list's and the compaction log's */
const DAY_1015 = {date:"2026-10-15", src:"from the open list and the PR list", title:"15 Oct (UTC): merges, a compaction round, and a re-run that waited for nothing",
 lanes:[{id:"owner", name:"Owner gates", abbr:"Owner", sub:"Favio"},{id:"dir", name:"Director", abbr:"Dir", sub:"one list"},
  {id:"code", name:"Release code", abbr:"Code", sub:"lane"},{id:"checks", name:"Checks", abbr:"Check", sub:"CI · tests"},
  {id:"films", name:"Films", abbr:"Films", sub:"lane"},{id:"rev", name:"Reviews", abbr:"Rev", sub:"lane"},{id:"other", name:"Other lanes", abbr:"Other", sub:"not named"}],
 events:[
  ["03:37","dir","public","0.4.5 is released on Favio’s go: the tag, the release and the site"],
  ["~08:40","rev","","The reviewer session missed a pull request: its timer does not fire while it is idle. A message wakes it; from now on every lane messages it on each new head"],
  ["","checks","","The first 0.4.6 pull request passes the full suite on the build machine, and every review says MERGE"],
  ["09:17","code","merge","Merges the first 0.4.6 pull request: tests and setup on other machines"],
  ["09:54","code","merge","Merges files stored byte for byte, with no line endings rewritten at checkout"],
  ["10:15","code","merge","Merges a skipped cut walk as a warning, and sturdier test deadlines"],
  ["10:20","dir","","A CI job fails on a public fix pull request, and the director re-runs it before reading its log"],
  ["10:23","code","merge","Merges small items from the 0.4.6 plan"],
  ["10:36","checks","","The re-run is cancelled after 15.6 minutes. The log had the cause: an icon lookup waits 38.5 s against a 30 s limit, so it fails every time"],
  ["","dir","public","On Favio’s yes, the fix-only public pull request merges"],
  ["11:23","code","merge","Merges the icon fix: a misspelled name gets its suggestion from the local index, before any fetch"],
  ["11:54","owner","","Favio starts a compaction round, one lane after another"],
  ["11:56","code","","Compacts: an 18,606-character summary that names its state file"],
  ["11:56","rev","","Compacts: 16,900 characters, names its state file"],
  ["11:56","other","","A lane not named here compacts: 18,172 characters, names its state file"],
  ["11:59","code","merge","Merges a report of .gitattributes lines git ignores, and a size-read test that runs on software graphics"],
  ["12:00","other","","Another lane compacts: 15,721 characters, names its state file"],
  ["12:05","films","","Compacts: 18,082 characters, names its state file. Then it sits idle, because a compaction does not start a turn"],
  ["","dir","","Checks the round: the rules card and each session’s own state file arrived whole in all four sessions checked"],
  ["","dir","","Messages the films lane to resume from its state file, and writes the rule: a compacted lane needs a message"],
  ["","checks","","The new overlap check, run on the film Favio caught, reports 0:45.50 to 0:47.23"],
  ["","rev","","The reviewer session on the overlap check: FIX FIRST"],
  ["","checks","","Round 2 of the overlap check: no false alarm over 43 projects and 10 templates laid out in portrait"],
  ["","rev","","The reviewer session: MERGE at the new head"],
  ["15:07","code","merge","Merges the text-over-text check, for 0.4.6"]
 ].map(([t, lane, gate, what]) => ({t, lane, gate, what}))};

(function replay() {
  const BASE = [
    {id:"owner", name:"Owner gates", abbr:"Owner", sub:"Favio"},
    {id:"main", name:"Main session", abbr:"Main", sub:"Opus 5.5"},
    {id:"opus", name:"Opus agents", abbr:"Opus", sub:"builds"},
    {id:"sonnet", name:"Sonnet workers", abbr:"Sonnet", sub:"Mac · evals"},
    {id:"haiku", name:"Haiku", abbr:"Haiku", sub:"lookups"},
    {id:"fable", name:"Fable", abbr:"Fable", sub:"reviews"},
    {id:"devin", name:"Devin cloud", abbr:"Devin", sub:"one machine"},
    {id:"creative", name:"Creative session", abbr:"Films", sub:"short films"}
  ];
  const GATES = {merge:"Merge gate · Favio’s yes", public:"Public gate · Favio’s yes", spend:"Spend gate · Favio’s yes"};
  const laneOf = e => {
    const l = String(e.lane || "").toLowerCase().trim(), m = String(e.model || "").toLowerCase();
    const byModel = s => (s.match(/fable|haiku|sonnet|opus/) || [null])[0];
    if (BASE.some(x => x.id === l)) return l;
    if (/^(favio|owner|owner gates|gates|human)$/.test(l)) return "owner";
    if (/^(main|main session|director)$/.test(l)) return "main";
    if (/devin/.test(l)) return "devin";
    if (/project|cloud/.test(l)) return "project";
    if (/agent|worker|sub/.test(l)) return byModel(m) || l;
    return byModel(l) || l || "other";
  };
  const normGate = g => { const s = String(g || "").toLowerCase().trim(); return !s ? "" : GATES[s] ? s : "public"; };
  const TRE = /^\s*(~)?\s*(\d{1,2}):(\d{2})\s*$/;
  const fmt = (min, ap) => (ap ? "~" : "") + String(Math.floor(min / 60) % 24).padStart(2, "0") + ":" + String(min % 60).padStart(2, "0");

  function norm(raw) {
    const own = raw.lanes, ownName = id => (own.find(l => l.id === id) || {}).name || id;
    const E = arr(raw.events).filter(e => e && (e.what || e.t)).map(e => {
      const m = TRE.exec(String(e.t || ""));
      return {min: m ? (+m[2]) * 60 + (+m[3]) : null, ap: !!(m && m[1]), lane: own ? e.lane : laneOf(e), laneRaw: String(e.lane || ""), model: own ? ownName(e.lane) : String(e.model || ""),
        what: String(e.what || ""), gate: normGate(e.gate), gateRaw: String(e.gate || ""), between: Array.isArray(e.between) ? e.between : null, when: String(e.when || "")};
    });
    const timed = E.filter(e => e.min != null).map(e => e.min);
    let start = timed.length ? Math.floor(Math.min(...timed) / 60) * 60 : 0, end = timed.length ? Math.ceil((Math.max(...timed) + 1) / 60) * 60 : 24 * 60;
    if (E.length && E[0].min == null) start = Math.max(0, start - 60);
    if (E.length && E[E.length - 1].min == null) end = Math.min(raw.dayNames && raw.dayNames.length > 1 ? Infinity : 24 * 60, end + 60);
    if (end - start < 120) end = Math.min(24 * 60, start + 120);
    E.forEach(e => { if (e.min != null) { e.pos = e.min; e.label = fmt(e.min, e.ap); } });
    for (let i = 0; i < E.length;) {
      if (E[i].min != null) { i++; continue; }
      let j = i; while (j < E.length && E[j].min == null) j++;
      const prev = i > 0 ? E[i - 1] : null, next = j < E.length ? E[j] : null;
      const lo = prev ? prev.pos : start, hi = next ? next.pos : end, cnt = j - i;
      for (let k = i; k < j; k++) {
        const e = E[k];
        e.pos = lo + (hi - lo) * (k - i + 1) / (cnt + 1);
        let a, b;
        if (e.between) { a = String(e.between[0] || ""); b = String(e.between[1] || ""); }
        else { a = prev ? prev.label : ""; b = next ? next.label : ""; }
        e.win = e.when ? e.when : a && b ? (own ? `${a} to ${b}` : `${a}–${b}`) : b ? `before ${b}` : a ? `after ${a}` : "time not logged";
        e.label = "";
      }
      i = j;
    }
    const lanes = (own || BASE).slice();
    E.forEach(e => { if (!lanes.some(l => l.id === e.lane)) lanes.push({id:e.lane, name:e.laneRaw || e.lane, abbr:(e.laneRaw || e.lane).slice(0, 6), sub:""}); });
    return {date: String(raw.date || raw._id || ""), title: String(raw.title || ""), E, lanes, start, end, dayNames: arr(raw.dayNames)};
  }

  const root = $("#rp"), sticky = $("#rpSticky"), stage = $("#rpStage"), nowEl = $("#rpNow");
  const clockEl = $("#rpClock"), clockS = $("#rpClockS"), titleEl = $("#rpTitle"), scrub = $("#rpScrub"), cntEl = $("#rpCount");
  const rows = $("#rpRows");
  const narrowQ = window.matchMedia("(max-width:640px)");
  let D = null, dots = [], gmks = [], nowLine = null, tie = null, idx = -1, frac = 0;
  const STEP = () => narrowQ.matches ? 52 : 60;
  const pct = p => (p - D.start) / (D.end - D.start) * 100;
  const X = p => `calc(10px + (100% - 20px) * ${(pct(p) / 100).toFixed(5)})`;
  const dtag = e => D && D.dayNames.length > 1 ? D.dayNames[e.pos >= 1440 ? 1 : 0] : "";
  const withDay = (s, e) => dtag(e) ? `${s} · ${dtag(e)}` : s;
  const laneName = id => { const l = D.lanes.find(x => x.id === id); return l ? l.name : id; };

  function build() {
    const lw = narrowQ.matches ? 54 : 184;
    const lh = Math.max(narrowQ.matches ? 20 : 26, Math.min(narrowQ.matches ? 27 : 38, Math.floor((window.innerHeight - (narrowQ.matches ? 420 : 470)) / D.lanes.length)));
    const span = (D.end - D.start) / 60, every = narrowQ.matches ? (span <= 16 ? 2 : 6) : (span <= 8 ? 1 : span <= 16 ? 2 : 3);
    stage.style.setProperty("--lw", lw + "px"); stage.style.setProperty("--lh", lh + "px");
    stage.style.setProperty("--hw", (100 / span) + "%");
    const used = new Set(D.E.map(e => e.lane)); D.E.forEach(e => { if (e.gate) used.add("owner"); });
    let ticks = "";
    for (let h = Math.ceil(D.start / 60 / every) * every; h <= D.end / 60; h += every) ticks += `<span style="left:${X(h * 60)}"${h > 0 && h % 24 === 0 && D.dayNames[h / 24] ? ' class="dayb"' : ""}>${h > 0 && h % 24 === 0 && D.dayNames[h / 24] ? D.dayNames[h / 24] : String(h % 24).padStart(2, "0") + ":00"}</span>`;
    let h = `<div class="rp-axis"><div></div><div class="ticks">${ticks}</div></div><div class="rp-lanes" id="rpLanes">`;
    D.lanes.forEach(l => {
      h += `<div class="rp-lane ${l.id === "owner" ? "owner" : ""} ${used.has(l.id) ? "" : "idle"}" data-lane="${esc(l.id)}"><div class="ln"><span class="full">${esc(l.name)}</span><span class="abbr">${esc(l.abbr)}</span>${l.sub ? `<small>${esc(l.sub)}</small>` : ""}</div><div class="tr">`;
      D.E.forEach((e, i) => {
        if (e.lane === l.id && !(l.id === "owner" && e.gate)) h += `<i class="dot ${e.min == null ? "un" : e.ap ? "ap" : ""} ${/^(main|owner|dir)$/.test(e.lane) ? "m-main" : ""}" data-i="${i}" style="left:${X(e.pos)}"></i>`;
        if (l.id === "owner" && e.gate) h += `<i class="gmk ${e.gate}" data-i="${i}" style="left:${X(e.pos)}"></i>`;
      });
      h += `</div></div>`;
    });
    h += `<div class="rp-tie" id="rpTie" hidden></div><div class="rp-now-line" id="rpLine" style="left:calc(${lw}px + 0%)"></div></div>`;
    stage.innerHTML = h;
    dots = [...stage.querySelectorAll(".dot")]; gmks = [...stage.querySelectorAll(".gmk")];
    nowLine = $("#rpLine"); tie = $("#rpTie");
    root.style.height = `calc(100vh + ${D.E.length * STEP()}px)`;
    root.style.height = `calc(100svh + ${D.E.length * STEP()}px)`;
    scrub.max = Math.max(0, D.E.length - 1);
    titleEl.textContent = D.title;
    rows.innerHTML = D.E.map(e => `<tr><td class="n">${esc(withDay(e.label || e.win, e))}</td><td>${esc(laneName(e.lane))}${e.model ? `<small style="display:block;color:var(--text-3)">${esc(e.model)}</small>` : ""}</td><td>${links(esc(e.what))}</td><td class="gate">${e.gate ? `<i class="gm ${e.gate}" aria-hidden="true"></i> ${esc(e.gateRaw || e.gate)}` : ""}</td></tr>`).join("");
    idx = -1; update(true);
  }

  function lineX(p) { const lw = parseFloat(stage.style.getPropertyValue("--lw")); return `calc(${lw + 10}px + (100% - ${lw + 20}px) * ${(pct(p) / 100).toFixed(5)})`; }
  function progress() {
    const r = root.getBoundingClientRect(), top = TOP, len = root.offsetHeight - window.innerHeight + top;
    return Math.max(0, Math.min(1, (top - r.top) / Math.max(1, len)));
  }
  function update(force) {
    if (!D || !D.E.length) return;
    const n = D.E.length, f = progress() * n, i = Math.min(n - 1, Math.floor(f));
    frac = Math.min(1, Math.max(0, f - i));
    const a = D.E[i], b = D.E[Math.min(n - 1, i + 1)];
    nowLine.style.left = lineX(a.pos + (b.pos - a.pos) * (i < n - 1 ? frac : 0));
    if (i === idx && !force) return;
    idx = i;
    dots.forEach(d => { const k = +d.dataset.i; d.classList.toggle("past", k < i); d.classList.toggle("cur", k === i); });
    gmks.forEach(d => { const k = +d.dataset.i; d.classList.toggle("past", k < i); d.classList.toggle("cur", k === i); });
    if (a.gate && a.lane !== "owner") {
      const lanesEl = $("#rpLanes"), lh = parseFloat(stage.style.getPropertyValue("--lh")), li = D.lanes.findIndex(l => l.id === a.lane), oi = D.lanes.findIndex(l => l.id === "owner");
      tie.hidden = false; tie.style.left = lineX(a.pos); tie.style.top = (Math.min(li, oi) * lh + lh / 2) + "px"; tie.style.height = (Math.abs(li - oi) * lh) + "px";
    } else tie.hidden = true;
    if (a.label) { clockEl.className = "c"; clockEl.textContent = a.label; clockS.textContent = withDay(a.ap ? "approximate, as logged" : "logged time", a); }
    else { clockEl.className = "c win"; clockEl.textContent = /\d:\d/.test(a.win) ? a.win.replace(/–/g, " – ") : a.win; clockS.textContent = withDay("in order · time not logged", a); }
    scrub.value = i; cntEl.textContent = `${String(i + 1).padStart(2, "0")} / ${String(n).padStart(2, "0")}`;
    const prev = D.E.slice(Math.max(0, i - 3), i).reverse();
    nowEl.innerHTML = `<div class="rp-card"><div class="meta"><span style="color:var(--text-2)">${esc(withDay(a.label || a.win, a))}</span>${a.model === laneName(a.lane) ? "" : `<span>${esc(laneName(a.lane))}</span>`}${chip(a.model, modelCls(a.model))}</div>
      <p class="what">${links(esc(a.what))}</p>${a.gate ? `<div class="gateline"><i class="gm ${a.gate}" aria-hidden="true"></i>${esc(GATES[a.gate])}</div>` : ""}</div>
      <div class="rp-prev"><div class="kick" style="margin-bottom:4px">Just before</div><ol>${prev.length ? prev.map(e => `<li><i>${esc(e.label || "–")}</i><span>${esc(e.what)}</span></li>`).join("") : `<li><i>·</i><span>The day starts here.</span></li>`}
      ${i < n - 1 ? `<li class="nx"><i>next</i><span>${esc(D.E[i + 1].what)}</span></li>` : ""}</ol></div>`;
  }
  let ticking = false;
  window.addEventListener("scroll", () => { if (!ticking) { ticking = true; requestAnimationFrame(() => { ticking = false; update(false); }); } }, {passive:true});
  function goTo(i) {
    if (!D) return;
    const n = D.E.length; i = Math.max(0, Math.min(n - 1, i));
    const len = root.offsetHeight - window.innerHeight + TOP, top0 = root.getBoundingClientRect().top + window.scrollY - TOP;
    window.scrollTo({top: top0 + (i + .5) / n * len, behavior: reduced ? "auto" : "smooth"});
  }
  $("#rpPrev").addEventListener("click", () => goTo(idx - 1));
  $("#rpNext").addEventListener("click", () => goTo(idx + 1));
  scrub.addEventListener("input", () => { const n = D.E.length, len = root.offsetHeight - window.innerHeight + TOP, top0 = root.getBoundingClientRect().top + window.scrollY - TOP;
    window.scrollTo({top: top0 + (+scrub.value + .5) / n * len, behavior:"auto"}); });

  const DAYS = [DAY_0909, DAY_1011, DAY_1015], pickBtns = [...document.querySelectorAll(".rp-day")];
  function pickDay(i) { pickBtns.forEach((x, j) => x.setAttribute("aria-pressed", j === i ? "true" : "false")); $(".rp-src").textContent = DAYS[i].src || "from the day log"; D = norm(DAYS[i]); build(); }
  pickBtns.forEach((x, i) => x.addEventListener("click", () => { pickDay(i); const r = root.getBoundingClientRect(); if (r.top < 0) window.scrollTo({top: r.top + window.scrollY - TOP, behavior: "auto"}); }));
  pickDay(0);
  let rz; window.addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => { if (D) build(); }, 150); });
})();

/* ================= 03 SWITCHBOARD ================= */
(function switchboard() {
  const MODELS = [["haiku","Haiku 5.5","Explore · researcher"],["sonnet","Sonnet 5.5","worker"],["opus","Opus 5.5","creative · builds"],["fable","Fable 5.1","reviewer"],["jev","Jev","TypeSafe"]];
  const TASKS = [
    {t:"A decision point", m:"fable", why:"Fable 5.1 reviews independently at decision points and advises before big plans. Every use is logged.",
     ex:"#24 render stall: FIX FIRST twice. A CHANGELOG entry in the wrong release, an unbacked “0.4 of a core” claim, a wrong 5% that should be ~10%, a false-fire risk on a rejected CDP call. All fixed, then merged.", rec:true},
    {t:"Research a fact", m:"haiku", why:"Haiku 5.5 runs the Explore and researcher agents: lookups, docs, web and browser work.",
     ex:"Reading the primary source in a real browser when WebFetch is refused: the first step of every Nobel lab.", rec:false},
    {t:"Build a film", m:"opus", why:"Creative and visual work, claims ledgers, hard debugging and film builds stay on Opus 5.5.",
     ex:"The creative session’s short films build headless with claude -p on Opus: the API key set for that one command, a cost cap, 75 minutes.", rec:true},
    {t:"Triage yes/no", m:"jev", why:"Jev (TypeSafe) makes tiny typed yes/no calls, a few thousandths of a cent each, only through one wrapper, and what it returns is a suggestion.",
     ex:"Dedup suggestions, 8 Oct: 57 of 65 decided, all right. Favio’s spot check: 10/10. The whole evaluation: $0.02.", rec:true},
    {t:"Apply a decided fix", m:"sonnet", why:"Sonnet 5.5 is the worker: Mac test runs, decided fixes, merges, eval runs.",
     ex:"A Mac review: run_all --changed plus the PR’s own suites, compared with main, before Favio’s yes.", rec:false}
  ];
  const tasksEl = $("#swTasks"), modelsEl = $("#swModels"), sv = $("#swsvg"), read = $("#swRead");
  const ROW = 56, H = ROW * 5;
  let active = 0, cables = [];
  TASKS.forEach((t,i) => {
    const b = document.createElement("button"); b.type = "button"; b.className = "sw-task"; b.textContent = t.t;
    b.setAttribute("aria-pressed", i === 0 ? "true" : "false");
    b.addEventListener("click", () => pick(i, true));
    tasksEl.appendChild(b);
  });
  modelsEl.innerHTML = MODELS.map(m => `<div class="sw-model" data-m="${m[0]}"><span>${m[1]}<small>${m[2]}</small></span></div>`).join("");
  function draw() {
    const W = Math.max(56, sv.clientWidth || 200);
    sv.setAttribute("viewBox", `0 0 ${W} ${H}`); sv.style.height = H + "px";
    sv.innerHTML = "";
    cables = TASKS.map((t,i) => {
      const y1 = ROW*i + ROW/2, y2 = ROW*MODELS.findIndex(m => m[0] === t.m) + ROW/2;
      const sag = Math.max(y1,y2) + 26 + Math.abs(y1-y2)*.12;
      const p = S("path", {d:`M8,${y1} C${W*.35},${sag} ${W*.65},${sag} ${W-8},${y2}`, class:"cable"}, sv);
      return {p, y1, y2};
    });
    TASKS.forEach((t,i) => S("circle", {cx:8, cy:ROW*i+ROW/2, r:5, class:"jack", "data-l":i}, sv));
    MODELS.forEach((m,i) => S("circle", {cx:W-8, cy:ROW*i+ROW/2, r:5, class:"jack", "data-r":m[0]}, sv));
    mark(false);
  }
  function mark(animate) {
    const t = TASKS[active];
    cables.forEach((c,i) => {
      c.p.classList.toggle("on", i === active);
      if (i === active) {
        sv.appendChild(c.p);
        const len = c.p.getTotalLength();
        c.p.style.transition = "none"; c.p.style.strokeDasharray = len;
        c.p.style.strokeDashoffset = animate && !reduced ? len : 0;
        if (animate && !reduced) { c.p.getBoundingClientRect(); c.p.style.transition = "stroke-dashoffset .7s cubic-bezier(.3,.7,.2,1)"; c.p.style.strokeDashoffset = 0; }
      } else { c.p.style.strokeDasharray = ""; c.p.style.strokeDashoffset = ""; }
    });
    sv.querySelectorAll(".jack").forEach(j => {
      const on = j.getAttribute("data-l") == active || j.getAttribute("data-r") === t.m;
      j.classList.toggle("on", on); if (on) sv.appendChild(j);
    });
    modelsEl.querySelectorAll(".sw-model").forEach(m => m.classList.toggle("on", m.dataset.m === t.m));
    const M = MODELS.find(m => m[0] === t.m);
    read.innerHTML = `<div><div class="lab">Routes to</div><div class="model">${M[1]}</div><p>${esc(t.why)}</p></div>
      <div><div class="lab">Example <span class="tag ${t.rec ? "amber" : "dim"}">${t.rec ? "on record" : "kind of job"}</span></div><p>${esc(t.ex)}</p></div>`;
  }
  function pick(i, animate) {
    active = i;
    [...tasksEl.children].forEach((b,j) => b.setAttribute("aria-pressed", j === i ? "true" : "false"));
    mark(animate);
  }
  draw();
  let t; window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(draw, 120); });
})();

/* ================= 04 RACE ================= */
(function race() {
  const V = [
    {n:"The film itself", s:"20 s of showreel", v:20, film:true},
    {n:"Mac", s:"6-core i5, GPU", v:89},
    {n:"Devin cloud", s:"8 cores · setup 23 s from a ready snapshot", v:124},
    {n:"Claude cloud", s:"4 CPU · Playwright CDN blocked by default", v:375}
  ];
  const MAX = 375, lanes = $("#raceLanes"), clockEl = $("#raceClock");
  lanes.innerHTML = V.map(r => `<div><div class="rl-top"><b>${r.n} <small>${r.s}</small></b><span class="ratio">${r.film ? "real time" : (r.v/20).toFixed(1) + "× the film’s length"}</span></div>
    <div class="track${r.film ? " film" : ""}"><div class="fill" style="width:${r.v/MAX*100}%"></div><span class="t">${r.v} s</span></div></div>`).join("");
  const fills = [...lanes.querySelectorAll(".fill")], labels = [...lanes.querySelectorAll(".t")];
  let raf = 0;
  $("#raceBtn").addEventListener("click", () => {
    cancelAnimationFrame(raf);
    if (reduced) return;
    const start = performance.now(), SPEED = 30;
    (function step(now) {
      const t = Math.min(MAX, (now - start)/1000 * SPEED);
      fills.forEach((f,i) => { const v = Math.min(V[i].v, t); f.style.width = v/MAX*100 + "%"; labels[i].textContent = (t >= V[i].v ? V[i].v : Math.floor(v)) + " s"; labels[i].style.color = t >= V[i].v ? "var(--amber)" : ""; });
      clockEl.textContent = Math.floor(t) + " s";
      if (t < MAX) raf = requestAnimationFrame(step); else { clockEl.textContent = "375 s"; labels.forEach(l => l.style.color = ""); }
    })(start);
  });
  const JOBS = ["The full suite","#24 Linux check","Flag experiment","Linux-only flag build","A test fix (no LaTeX)","#29 splice","Setup fix","Setup fix","Chapter-mode data","Auto-workers study","Audio-sync fix"];
  $("#jobs").innerHTML = JOBS.map(j => `<div>${j}</div>`).join("") + `<div class="wide">A film lab’s data toys: an independent review, fixes, the page, a data export</div>`;
})();

/* ================= 05 PIPELINE ================= */
(function pipeline() {
  const ST = [
    {t:"Issue", who:"public repo", s:"Milestone, labels, safety check", d:"Filed on the public repo with milestone and labels, through an issue tool that runs a safety check first.", ev:"Issues #38–#48 filed on 9 Oct: #38–#43 by morning, #44–#48 at ~11:20."},
    {t:"Draft PR", who:"private working repo", s:"“Closes …showtime#N”", d:"A draft PR on the private working repo that says “Closes FavioVazquez/showtime#N”.", ev:"Cloud Project PRs carry the exact Mac commands in the body."},
    {t:"First pass", who:"Review session", s:"Reads the diff; never merges", d:"The review session takes the first pass on the diff of cloud PRs. It never merges.", ev:"It is also the only session that runs the shared PR watcher."},
    {t:"Mac review", who:"the Mac", s:"run_all --changed + PR suites", d:"run_all --changed plus the PR’s own suites, compared with main.", ev:"Why: one merge broke main’s scoreboard test; an ffmpeg audio fix tested only on Linux was 11–21 ms off on macOS."},
    {t:"Fable", who:"Fable 5.1", s:"Decision points only", d:"An independent review, only where a decision hangs on it.", ev:"The render-stall fix (#24): FIX FIRST twice, four catches, all fixed."},
    {t:"Favio’s yes", who:"Favio, in chat", s:"Each time, from him directly", d:"A yes in chat for each merge. A relayed approval doesn’t count.", ev:"Every 9 Oct merge went through his gate: a one-night rule to merge what passes the Mac review, standing yeses he gave by name, or a yes on the spot."},
    {t:"Merge", who:"main session", s:"Merge commit, issue marked fixed", d:"A merge commit; then the issue tool marks the public issue fixed.", ev:"16 merges on 9 Oct, each through Favio’s gate."},
    {t:"Release", who:"public repo", s:"One clean commit", d:"A release is one clean commit on the public repo, built by a script in a separate publish repo.", ev:"0.4.2 shipped on 11 Oct, once the full tier was green on all four systems."}
  ];
  const pipe = $("#pipe"), read = $("#pipeRead");
  let cur = 0, timer = 0;
  pipe.innerHTML = ST.map((s,i) => `<button type="button" class="pstep" data-i="${i}"><span class="n">${String(i+1).padStart(2,"0")}</span><b>${esc(s.t)}</b><span>${esc(s.s)}</span></button>`).join("");
  read.innerHTML = `<div id="prA"></div><div id="prB"></div><div class="ctl"><button class="btn" type="button" id="pPrev" aria-label="Previous gate">Prev</button><button class="btn" type="button" id="pNext" aria-label="Next gate">Next</button><button class="btn" type="button" id="pWalk">Walk it</button></div>`;
  function go(i) {
    cur = (i + ST.length) % ST.length;
    pipe.querySelectorAll(".pstep").forEach((b,j) => { b.classList.toggle("on", j === cur); b.classList.toggle("past", j < cur); b.setAttribute("aria-current", j === cur ? "step" : "false"); });
    const s = ST[cur];
    $("#prA").innerHTML = `<div class="lab">Gate ${cur+1} of 8 · ${esc(s.who)}</div><p style="color:var(--text);font-size:var(--s-lg);line-height:1.35">${esc(s.d)}</p>`;
    $("#prB").innerHTML = `<div class="lab">Evidence</div><p>${links(esc(s.ev))}</p>`;
  }
  pipe.addEventListener("click", e => { const b = e.target.closest(".pstep"); if (b) { clearInterval(timer); go(+b.dataset.i); } });
  read.addEventListener("click", e => {
    if (e.target.id === "pPrev") { clearInterval(timer); go(cur-1); }
    if (e.target.id === "pNext") { clearInterval(timer); go(cur+1); }
    if (e.target.id === "pWalk") { clearInterval(timer); go(0); if (!reduced) timer = setInterval(() => { if (cur >= ST.length-1) clearInterval(timer); else go(cur+1); }, 1600); }
  });
  go(0);
  const M = [["#8","Voice engines","night rule · 01:35"],["#28","--fit estimate","night rule"],["—","Tests skip without LaTeX","night rule"],["#33","“Full crew”","night rule"],["#27","Audio mix validation","night rule"],["#34","Sound designer","morning; not itemised"],["#35","Eval graders","his OK"],["#24","Render stall (the case study)","his 07:20 rule"],["#29","Splice 9:16","standing, 07:20"],["#39, #40","Setup","standing, 07:20"],["#42","Crew turn caps","yes, ~11:20"],["—","Guard test for #24","yes, ~11:20"],["—","Load flakes","yes, ~11:20"],["—","CHANGELOG credit for #8","OK asked ~11:45"],["#38","Edit render audio sync","standing, ~12:05"],["#41","Auto workers","yes, that night or sooner"]];
  $("#merges").innerHTML = M.map(m => `<tr class="${m[0]==="#24"?"hl":""}"><td class="n">${links(m[0])}</td><td>${esc(m[1])}</td><td style="font-family:var(--f-mono);font-size:12.5px;color:var(--text-3);white-space:nowrap">${esc(m[2])}</td></tr>`).join("");
})();

/* jev pips */
$("#jevPips").innerHTML = Array.from({length:65}, (_,i) => `<i class="${i<57?"f":""}"></i>`).join("");

/* ================= 07/08 CASE STEPPERS ================= */
function delta(v, min, max, cls, bare) {
  const z = (0 - min)/(max - min)*100, x = (v - min)/(max - min)*100;
  const l = Math.min(z,x), w = Math.abs(x - z);
  return `<div class="delta"><div class="ax"></div><div class="z"></div><div class="bar ${cls}" style="left:${l}%;width:${w}%"></div>
    ${bare ? "" : `<div class="lb" style="left:0%;transform:none">${min}%</div><div class="lb" style="left:${z}%">0</div><div class="lb" style="left:100%;transform:translateX(-100%)">+${max}%</div>`}</div>`;
}
function stepper(rootSel, kicker, steps) {
  const root = $(rootSel);
  root.innerHTML = `<ol class="case-rail">${steps.map((s,i) => `<li><button type="button" class="cstep" data-i="${i}"><span class="n">${String(i+1).padStart(2,"0")}</span><b>${esc(s.t)}</b><span>${s.d}</span></button></li>`).join("")}</ol>
    <div class="case-mon"><div class="case-mon-in" aria-live="polite"><div class="mon-k"><span>${esc(kicker)}</span><b class="mk-n"></b></div><h3 class="mon-t"></h3><div class="mon-v"></div>
    <div class="mon-ctl"><button class="btn" type="button" data-a="-1">Prev</button><button class="btn" type="button" data-a="1">Next</button></div></div></div>`;
  let cur = 0;
  function go(i) {
    cur = Math.max(0, Math.min(steps.length-1, i));
    root.querySelectorAll(".cstep").forEach((b,j) => b.setAttribute("aria-current", j === cur ? "step" : "false"));
    root.querySelector(".mk-n").textContent = `Step ${String(cur+1).padStart(2,"0")} / ${String(steps.length).padStart(2,"0")}`;
    root.querySelector(".mon-t").textContent = steps[cur].t;
    root.querySelector(".mon-v").innerHTML = steps[cur].v;
  }
  root.addEventListener("click", e => {
    const b = e.target.closest(".cstep"); if (b) go(+b.dataset.i);
    const a = e.target.closest("[data-a]"); if (a) go(cur + +a.dataset.a);
  });
  root.querySelector(".case-rail").addEventListener("keydown", e => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); go(cur + (e.key === "ArrowDown" ? 1 : -1)); root.querySelectorAll(".cstep")[cur].focus(); }
  });
  go(0);
}
stepper("#caseStall", "Issue #24", [
  {t:"Symptom", d:"Renders and checks could hang for 10+ minutes on macOS CI.",
   v:`<div class="screen"><div class="cap">Frames delivered</div><div class="big-n red">10+ min</div><div class="frames" aria-hidden="true">${"<i></i>".repeat(7)}${'<i class="s"></i>'.repeat(5)}</div><p class="note" style="margin:8px 0 0">A render that stops getting frames and never says so.</p></div>`},
  {t:"The fix: a stuck-frame guard", d:"A screenshot whose browser does no drawing work for 30 s × pace fails; render redraws in a new browser.",
   v:`<div class="screen"><div class="cap">Guard rule</div><div class="big-n cyan">30 s × pace</div><p style="margin:8px 0 0;color:var(--text-2)">No drawing work for that long: the screenshot fails, and the render redraws the frame in a new browser.</p></div>`},
  {t:"Linux: 9% slower", d:"The fix had dropped Chrome’s <code>--disable-frame-rate-limit</code>.",
   v:`<div class="screen"><div class="cap">Speed vs main · Linux · without the flag</div><div class="big-n red">−9%</div>${delta(-9,-25,25,"neg")}</div>`},
  {t:"Flag back on Linux: 5% faster", d:"5% faster than main, and the stall tests pass.",
   v:`<div class="screen"><div class="cap">Speed vs main · Linux · with the flag</div><div class="big-n green">+5%</div>${delta(5,-25,25,"pos")}<p class="note" style="margin:8px 0 0"><span class="lamp on"></span>stall tests pass</p></div>`},
  {t:"macOS: the flag blinds the guard", d:"The renderer kept working after the GPU process stopped, so the guard never fired, and the flag gave ~2% speed for +22% CPU.",
   v:`<div class="screen"><div class="cap">macOS · with the flag</div>
     <div class="drow"><span>speed</span>${delta(2,-25,25,"pos",1)}<span class="v" style="color:var(--green)">~2%</span></div>
     <div class="drow"><span>CPU</span>${delta(22,-25,25,"cost",1)}<span class="v" style="color:var(--red)">+22%</span></div>
     <p style="margin:10px 0 0"><span class="lamp off"></span>guard never fired</p></div>`},
  {t:"Decision from data", d:"The flag on Linux only.",
   v:`<div class="matrix"><div class="h">Linux</div><div><span class="lamp on"></span>flag on · +5%, guard works</div><div class="h">macOS</div><div><span class="lamp off"></span>flag off · guard works</div></div>`},
  {t:"Proof on the Mac", d:"<code>test_render</code> on main timed out at 900 s; on the fix it passed in 760 s.",
   v:`<div class="screen"><div class="cap">test_render on the Mac · seconds</div>
     <div class="hbar"><span>main</span><span class="bt"><i style="width:100%;background:repeating-linear-gradient(135deg,var(--red) 0 4px,transparent 4px 7px)"></i></span><span class="v">900 s</span></div>
     <div class="hbar amber" style="margin-top:8px"><span>the fix</span><span class="bt"><i style="width:84.4%"></i></span><span class="v">760 s</span></div>
     <p class="note" style="margin:10px 0 0"><span class="lamp bad"></span>main: timed out &nbsp; <span class="lamp on"></span>fix: passed</p></div>`},
  {t:"Fable, then the merge", d:"FIX FIRST twice: a CHANGELOG entry in the wrong release, an unbacked “0.4 of a core” claim, a wrong 5% that should be ~10%, a false-fire risk on a rejected CDP call. All fixed, then merged.",
   v:`<div class="screen"><div><span class="stamp">FIX FIRST</span> <span class="stamp">FIX FIRST</span> <span class="stamp g">MERGED</span></div>
     <ol class="catches" style="margin-top:10px"><li>CHANGELOG entry in the wrong release</li><li>Unbacked “0.4 of a core” claim</li><li>A wrong 5% that should be ~10%</li><li>False-fire risk on a rejected CDP call</li></ol></div>`}
]);
/* ================= 09 FILMS ================= */
(function films() {
  const sw = {
    med:`<svg viewBox="0 0 300 136" preserveAspectRatio="xMidYMid slice"><defs><radialGradient id="gm" cx=".32" cy=".55" r=".55"><stop offset="0" stop-color="#3f6dff" stop-opacity=".75"/><stop offset="1" stop-color="#0a1130" stop-opacity="0"/></radialGradient></defs><rect width="300" height="136" fill="#0a1130"/><rect width="300" height="136" fill="url(#gm)"/><path d="M0 78 H70 l8-30 8 52 8-40 6 18 H160 l6-14 6 22 6-8 H300" fill="none" stroke="#a9c3ff" stroke-width="1.6"/><circle cx="96" cy="74" r="3" fill="#e6eeff"/></svg>`,
    phy:`<svg viewBox="0 0 300 136" preserveAspectRatio="xMidYMid slice"><rect width="300" height="136" fill="#16303a"/><rect y="60" width="300" height="30" fill="#24505a"/><rect y="90" width="300" height="46" fill="#3a6f72"/><path d="M0 60 Q75 52 150 60 T300 60" fill="none" stroke="#9fc9c1" stroke-width="1"/>${[...Array(12)].map((_,i)=>{const a=i/12*Math.PI*2;return `<line x1="212" y1="44" x2="${212+Math.cos(a)*30}" y2="${44+Math.sin(a)*30}" stroke="#eaf6f2" stroke-width="1" opacity=".7"/>`}).join("")}<circle cx="212" cy="44" r="5" fill="#fff"/></svg>`,
    chem:`<svg viewBox="0 0 300 136" preserveAspectRatio="xMidYMid slice"><rect width="300" height="136" fill="#e8dfcb"/>${[...Array(7)].map((_,i)=>`<line x1="22" y1="${30+i*12}" x2="${120-(i%3)*14}" y2="${30+i*12}" stroke="#4a3f30" stroke-width="2" opacity=".55"/>`).join("")}<polygon points="160,44 180,32 200,44 200,68 180,80 160,68" fill="none" stroke="#a8432c" stroke-width="2"/><polygon points="226,44 246,32 266,44 266,68 246,80 226,68" fill="none" stroke="#a8432c" stroke-width="2"/><line x1="213" y1="24" x2="213" y2="88" stroke="#4a3f30" stroke-dasharray="3 3"/><rect x="0" y="118" width="300" height="18" fill="#d9ceb5"/></svg>`,
    lit:`<svg viewBox="0 0 300 136" preserveAspectRatio="xMidYMid slice"><rect width="300" height="136" fill="#f1eee7"/><path d="M28 92 C70 40,110 112,150 66 S230 40,272 70 L274 76 C232 50,196 84,152 76 S74 56,30 98 Z" fill="#111"/><circle cx="268" cy="96" r="2.5" fill="#111"/><circle cx="252" cy="104" r="1.5" fill="#111"/></svg>`,
    wave:`<svg viewBox="0 0 300 136" preserveAspectRatio="xMidYMid slice"><rect width="300" height="136" fill="#e9e2cf"/><path d="M0 136 V96 C40 70,70 40,120 34 C150 30,176 44,170 62 C164 76,142 70,148 58 C120 66,128 96,170 100 C210 104,240 92,300 100 V136 Z" fill="#1d3a6b"/><path d="M120 34 C150 30,176 44,170 62" fill="none" stroke="#f6f1e4" stroke-width="3"/>${[0,1,2,3,4].map(i=>`<circle cx="${128+i*9}" cy="${35+(i%2)*3}" r="3.2" fill="#f6f1e4"/>`).join("")}<path d="M0 112 C60 104,120 118,300 108" fill="none" stroke="#7f9cc4" stroke-width="1.5"/><path d="M226 92 l14 -22 14 22 z" fill="#c9c2ae" stroke="#1d3a6b"/></svg>`,
    uv:`<svg viewBox="0 0 300 136" preserveAspectRatio="xMidYMid slice"><rect width="300" height="136" fill="#0e0a20"/><ellipse cx="150" cy="68" rx="138" ry="58" fill="none" stroke="#3b2f6e"/><line x1="12" y1="68" x2="288" y2="68" stroke="#3b2f6e"/>${[[40,50],[62,80],[90,40],[110,92],[132,60],[150,30],[168,84],[190,52],[206,100],[226,40],[244,70],[262,58],[80,62],[120,44],[180,70],[214,76],[98,104],[154,104]].map(([x,y],i)=>`<circle cx="${x}" cy="${y}" r="${1.4+(i%3)*.8}" fill="#c3b2ff" opacity="${.5+(i%4)*.12}"/>`).join("")}</svg>`
  };
  const F = [
    {sw:"med", h:"Medicine", sub:"Optogenetics", voice:"af_heart", look:"nocturne", music:"a composed underscore", shows:"A simulator with a heat budget, and a version that stops and asks."},
    {sw:"phy", h:"Physics", sub:"IceCube", voice:"am_michael at 1.08×", look:"tidewater", music:"a CC0 track", shows:"A 3D replay of a real 6 PeV event."},
    {sw:"chem", h:"Chemistry", sub:"", voice:"af_bella", look:"paperback", music:"a catalog track", shows:"Not socratic; 12 scenes in ~25 min by reusing fragments."},
    {sw:"lit", h:"Literature", sub:"", voice:"am_eric", look:"ink", music:"a CC0 classical recording", shows:"The ink kit, with no likeness of a living author."},
    {sw:"wave", h:"Inside the Great Wave", sub:"A woodblock print, in code", voice:"none", look:"a 3D world in code, the print projected at frame 0, ink draw-on", music:null, shows:"CPU only, no image model; a 22 s loop with no visible seam; three critic rounds, 9 should-fixes fixed; a 12 min render. It replaced a 2.5D parallax that had nothing behind the painting. Posted by Favio on 9 Oct."},
    {sw:"uv", h:"UV sky map", sub:"The creative session’s first film · 8 Oct", voice:null, look:null, music:null, shows:"53 min to make. Accurate but visually simple."}
  ];
  const dd = v => v == null ? `<dd class="nr">not recorded</dd>` : `<dd>${esc(v)}</dd>`;
  $("#reel").innerHTML = F.map(f => `<article class="film"><div class="swatch" role="img" aria-label="A swatch suggesting the look of ${esc(f.h)}">${sw[f.sw]}</div>
    <div class="body"><h3>${esc(f.h)}</h3>${f.sub ? `<div class="subj">${esc(f.sub)}</div>` : ""}
    <dl><dt>Voice</dt>${dd(f.voice)}<dt>Look</dt>${dd(f.look)}<dt>Music</dt>${dd(f.music)}</dl>
    <p class="shows">${esc(f.shows)}</p></div></article>`).join("");
})();

/* ================= 01 SITUATION FINDER =================
   Embedded runbooks, matched client-side. Commands are written as the
   memory and logs write them; nothing here is sent anywhere. */
(function finder() {
  const RB = [
    {id:"mac-review", t:"Review a PR on the Mac", keys:["review a pr on the mac","mac review","review a pr","test a pr","check a pr","run the tests"],
     tags:"review pr mac test tests suite run_all changed compare main verify worker",
     steps:["Merge main into the PR branch and test that merge, not the branch alone.","Run <b>run_all --changed</b>: it picks the test files the diff touches (a PR that adds an eval case can break the scoreboard’s case count).","Add the PR’s own suites, and compare every result with main.","Run test files through run_all: it uses showtime’s own environment. A bare system python3 can lack the audio libraries.","Heavy files (test_render, test_audio) time out at 900 s when three run at once: re-run them alone with a longer timeout.","Queue Mac reviews through one worker. Never wait on <b>pgrep -f run_all.py</b>: it matches the other waiters too."],
     cmds:[{c:"python skills/showtime/tests/run_all.py --changed main"},{c:"--timeout 2400", flag:true, n:"for a heavy file re-run alone"},{c:"ps -axo command | grep -E '^[^ ]*python[0-9.]* .*run_all\\.py'", n:"real runs only"}],
     model:"Sonnet 5.5", why:"A worker runs the review; the main session reads the verdict and asks for the merge.",
     gates:[], gnote:"None to review. The merge is its own gate.", see:[["#shipping","Shipping gates"],["#lessons","Scars: tests under load"],["#venues","Where work runs"]]},
    {id:"merge", t:"Merge a PR", keys:["merge a pr","merge","land a pr","ship a fix","merge the pr"],
     tags:"merge pr land ship yes approve standing main fixed milestone",
     steps:["The Mac review says MERGE, compared with main.","At a decision point only, a Fable review; apply its FIX FIRST items and re-check.","Ask Favio in chat and wait for his yes to this merge. A relayed yes doesn’t count; a standing yes covers only what he named.","A merge commit.","Keep the private working repo current, so the cloud Project sees current code.","Mark the public issue fixed, with the milestone."],
     cmds:[{tool:"git", c:"a merge commit on the working repo"},{tool:"the issue tool", c:"fixed N · marks the public issue fixed, with its milestone"}],
     model:"Opus 5.5 · main session", why:"The director merges after the yes; a Sonnet worker can carry a decided, mechanical merge.",
     gates:[["merge","Favio’s yes in chat, for this merge"]], see:[["#shipping","Issue to release"],["#guardrails","Approvals"]]},
    {id:"issue", t:"File an issue", keys:["file an issue","open an issue","report a bug","new issue","log a bug"],
     tags:"issue bug ticket github public label milestone dedup triage",
     steps:["Public issues live on FavioVazquez/showtime and go out only through the issue tool. It runs a public-safety check first: private names, paths and secrets.","Describe showtime’s behaviour only.","A milestone (0.4.2 next) and the existing labels. Favio’s queue is a label.","Public text waits for Favio’s yes. Jev can suggest a duplicate; it never decides.","On merge, the issue tool marks it fixed. At release, it writes the Closes lines."],
     cmds:[{tool:"the issue tool", c:"new · runs the safety check, then files"},{tool:"the issue tool", c:"fixed N · on merge, with the milestone"},{tool:"the issue tool", c:"closes · the Closes lines for a release"}],
     model:"Opus 5.5 · main session", why:"Agents never write to GitHub directly; the director files. Jev, through one wrapper, for dedup suggestions.",
     gates:[["public","Favio’s yes for public text"]], see:[["#shipping","Issue to release"],["#guardrails","Public surface"]]},
    {id:"prize", t:"A prize was announced", keys:["a prize was announced","nobel","prize","laureate","nobel lab"],
     tags:"prize nobel laureate award announced lab ledger toys explainer film footage claims",
     steps:["Favio picks the scope first (lab, explainer, short or not) and what stays out.","Read the primary source in a real browser when WebFetch is refused.","Claims ledger: every sentence sourced, quotes of 15 words or fewer, a “will not claim” list.","Toys on Devin with tests and sha-checked data; an independent review in a fresh session, started last.","Page (“guess first, then see”), script, storyboard; the critic on the board before any scene is built.","Footage: a rights check before a clip is used, and a speaker check before cutting.","Build and sound in parallel; then qa, the critic, Fable’s claims review.","Favio’s OK, then one public commit. He decides when and how it goes out."],
     cmds:[{c:"showtime check", n:"before the one render"},{c:"showtime qa", n:"on the finished cut"}],
     model:"Opus 5.5 for the ledger and the film", why:"Fetching: on 9 Oct the first Haiku pass at a lab’s pre-research failed on a 403, and Sonnet with curl reran it. Fable reviews the claims.",
     gates:[["public","one public commit, with Favio’s OK"]], see:[["#films","Films reel"],["#quality","Quality instruments"],["#lessons","Scars: a source behind a 403"]]},
    {id:"devin-lost", t:"Devin lost connection", keys:["devin lost connection","devin disconnected","connection dropped","connection lost","devin dropped","resume devin"],
     tags:"devin connection lost dropped disconnected resume cloud session turn offline",
     steps:["Don’t restart: a lost connection ends only the local turn, and the cloud session keeps its state.","The send script resumes the same session by itself, up to 5 tries.","By hand: resume from the folder that started the session.","Careful: -c goes to the account’s most recent cloud session. If a reviewer started after the builder, the follow-up lands on the reviewer.","Check whether a turn is still running before you send another."],
     cmds:[{c:"devin --cloud -c -p -- \"<prompt>\""},{c:"ps -axo command | grep -E '^devin --cloud'", n:"a turn is running while this matches"}],
     model:"Devin cloud", why:"Driven from the Mac by the main session.",
     gates:[], gnote:"None.", see:[["#venues","Devin, kept on one machine"],["#lessons","Scars: a resume that reached the wrong Devin"]]},
    {id:"devin-job", t:"Send Devin a job", keys:["send devin a job","start devin","ask devin","run on devin","devin follow up"],
     tags:"devin job start session send brief watch follow-up cloud",
     steps:["Every brief starts by pointing Devin at the shared memory repo, so it knows the rules.","Send it with the send script: one cloud session per folder; it refuses while a turn runs.","Tell Favio right away, with a read-only way to watch it.","After any send, read the pane back: a queued message can sit unsent."],
     cmds:[{tool:"the send script", c:"a prompt file and a tag · one cloud session per folder"}],
     model:"Devin cloud", why:"Builds, the full suite and long jobs; one machine for many turns.",
     gates:[], gnote:"None to start.", see:[["#venues","Where work runs"],["#lessons","Scars: messages that never left"]]},
    {id:"eval", t:"Run an eval", keys:["run an eval","plugin eval","eval","evaluation","hill climb","benchmark"],
     tags:"eval evaluation plugin benchmark grader case hill climb hillclimb score cost cap",
     steps:["Run a plugin eval whenever SKILL.md, a reference’s routing or a crew rule changes.","Run just the affected case, 3 runs, with a cost cap; runs in flight can overshoot the cap a little.","The whole suite before a release.","Prompt-only facts may not discriminate: scaffold real inputs, and check that “without” fails.","Hill-climbing: a train/test split, one root-cause patch per round, kept only if both scores rise; stop inside the noise. Not on saturated evals (≥ ~95%).","API spend needs Favio’s yes, with a cap."],
     cmds:[{tool:"claude plugin eval", c:"the affected case only, 3 runs, a cost cap"}],
     model:"Sonnet 5.5 runs it", why:"Fable advises before the plan; the human’s blind vote decides quality claims.",
     gates:[["spend","Favio’s yes, with a cap"]], see:[["#quality","Quality instruments"]]},
    {id:"film", t:"Make a short film", keys:["make a film","short film","make a short film","creative session","headless film"],
     tags:"film video short creative session headless claude make card topic pick",
     steps:["The creative session proposes film topics; Favio picks one in chat.","The film job takes the full run path: a headless claude -p on Opus, the API key set for that one command, a cost cap, 75 min.","Put --disallowedTools first, never before the prompt: it takes a list and swallows the prompt.","Estimate before fitting the voice: it prints “cut about N words” with no speech.","The card: the film, with every claim next to its source.","Favio judges it. If it goes out, he posts it himself, in his words. The main session files the lessons as showtime issues, with his yes."],
     cmds:[{c:"showtime voice script narration.md -o voice --fit 15 --estimate", n:"the estimate, no speech"}],
     model:"Opus 5.5 (headless)", why:"The creative session runs it; the film job is one claude -p command.",
     gates:[["spend","a cost cap per film"],["public","anything public: Favio’s yes"]], see:[["#films","Films reel"],["#lessons","Scars: a flag that ate the prompt"]]},
    {id:"release", t:"Cut a release", keys:["cut a release","release","publish a release","ship a version","tag a release"],
     tags:"release publish version tag npm registry public repo ship",
     steps:["Never push the working repo, or any integration or fix branch, to the public repo.","A release branch is built by a script in a separate publish repo, history kept.","A PR with milestone, assignee, skip-notes and Closes lines; CI including the 4-platform e2e.","Push the examples repo before merging the release PR.","Favio says merge: merge commit, never squash; tag and GitHub release.","Favio publishes npm and the MCP Registry himself."],
     cmds:[{tool:"a release script", c:"builds the release branch in the publish repo, history kept"}],
     model:"Sonnet 5.5 builds; the main session checks", why:"A release build is mechanical; the checks and the ask are the director’s.",
     gates:[["merge","Favio says merge"],["public","the release itself"]], see:[["#shipping","Issue to release"],["#guardrails","Public surface"]]},
    {id:"cloud-pr", t:"A cloud Project PR arrived", keys:["a cloud project pr arrived","cloud project pr","project pr","cloud pr","draft pr"],
     tags:"cloud project pr draft review first pass watcher device",
     steps:["The review session takes the first pass on the diff. It never merges, and only it runs the shared PR watcher.","The main session runs the tests on the Mac against main; bare clones give false failures.","Cloud threads never get device access: if one asks to connect, Favio denies it.","Messages for the cloud Project go through Favio, as paste-ready text.","Then the merge gate, as usual."],
     cmds:[],
     model:"Sonnet worker, then the Opus main session", why:"First pass by a background worker; the Mac check and the merge ask by the director.",
     gates:[["merge","Favio’s yes"]], see:[["#shipping","First pass, then Mac review"],["#guardrails","Interlocks"]]},
    {id:"keys", t:"Handle a key or secret", keys:["handle a key","api key","secret","token","credentials"],
     tags:"key secret token api credentials password config export billing",
     steps:["Keys live only in ~/.config, mode 600. Never print, paste or log one; check presence only.","Set an API key per command for a headless job; never export it, or interactive sessions move to API billing.","Git hooks and the issue tool block key contents; a new key file is added to both.","Calls to Jev go only through one wrapper."],
     cmds:[], model:"Any session", why:"The rule is the same for every model and machine.",
     gates:[], gnote:"None; it is an interlock, always on.", see:[["#guardrails","Keys"]]},
    {id:"overload", t:"The Mac is overloaded", keys:["the mac is overloaded","mac is slow","overloaded","tests time out","too many renders"],
     tags:"mac load slow overloaded timeout heavy renders cpu busy quiet",
     steps:["On the 6-core Mac, at most 2–3 CPU-heavy agents (renders, ASR, TTS) at once.","Heavy test files that time out at 900 s under load: re-run them alone.","Timing measurements wait for a quiet Mac.","Big parallel builds go to Devin cloud."],
     cmds:[{c:"--timeout 2400", flag:true, n:"for a heavy file re-run alone"}],
     model:"Sonnet worker queue", why:"One queue keeps reviews from starving each other.",
     gates:[], gnote:"None.", see:[["#venues","Where work runs"],["#lessons","Scars: tests under load"]]},
    {id:"send", t:"Send Favio a file", keys:["send favio a file","send the video","share with favio","deliver a file"],
     tags:"send file video deliver owner favio phone share",
     steps:["Look first: 2 fps contact sheets of every delivered aspect.","Copy it to the delivery folder the app can open; working folders don’t open there.","Videos for the phone stay at 30 MB or less.","HTML goes out as a link, not an attachment.","Send it as soon as it exists, with what it is and its review status."],
     cmds:[], model:"Main session", why:"Delivery is the director’s; the checks come first.",
     gates:[], gnote:"None to send privately.", see:[["#lessons","Scars: files Favio couldn’t open"]]},
    {id:"resume", t:"Resume after a compact", keys:["resume after a compact","resume","what is open","where were we","after a restart"],
     tags:"resume compact compaction restart open state plan overnight",
     steps:["Read OPEN.md first, then the release’s STATE.md RESUME block, then the day log, OVERNIGHT.md.","Check run journals, resume interrupted runs, send finished deliverables.","Re-arm session-only monitors: they die on restart.","Write each decision down as it is made."],
     cmds:[], model:"Main session", why:"State lives in files so that compactions and restarts lose nothing.",
     gates:[], gnote:"None.", see:[["#lessons","Scars: state in /tmp"]]},
    {id:"judge", t:"A small yes/no judgment", keys:["a small yes no judgment","yes or no","dedup","triage","classify"],
     tags:"jev typesafe yes no classify dedup duplicate triage label judgment",
     steps:["Small typed yes/no or choice calls over text go to Jev, only through one wrapper.","A few thousandths of a cent a call. It suggests; it never decides.","Good for issue dedup and triage."],
     cmds:[], model:"Jev (TypeSafe)", why:"57 of 65 dedup suggestions decided, all right, for $0.02 in the 8 Oct evaluation.",
     gates:[], gnote:"None.", see:[["#routing","Model routing"],["#quality","Jev evaluation"]]},
    {id:"fact", t:"Check a fact or a source", keys:["check a fact","fact check","verify a claim","source blocked","webfetch blocked"],
     tags:"fact check verify claim source blocked webfetch 403 paper citation number",
     steps:["Read the primary source in a real browser when a site blocks WebFetch.","Papers: curl with a browser User-Agent, NCBI E-utilities or Europe PMC.","Every number gets an independent reviewer; claims sit next to their sources.","Before anything public: Fable reviews the claims."],
     cmds:[], model:"Haiku for lookups; Opus or Fable to judge", why:"Lookups are cheap, so Haiku does them; what ships is judged on Opus or Fable.",
     gates:[], gnote:"None until it is public.", see:[["#quality","Quality instruments"],["#lessons","Scars: a source behind a 403"]]}
  ];
  const CHIPS = ["review a PR on the Mac","merge a PR","a prize was announced","Devin lost connection","file an issue","run an eval","resume after a compact"];
  const STOP = new Set("a an the to on in of for my i we is was do does how what when should with and or it its at by from this that be i'm im".split(" "));
  const SYN = {ship:["merge","release"],land:["merge"],disconnected:["connection","lost"],dropped:["connection","lost"],offline:["connection","lost"],
    nobel:["prize"],laureate:["prize"],award:["prize"],announced:["prize"],bug:["issue"],ticket:["issue"],evaluation:["eval"],benchmark:["eval"],grader:["eval"],graders:["eval"],
    pull:["pr"],tests:["test"],testing:["test"],secret:["key"],token:["key"],credentials:["key"],password:["key"],slow:["overloaded"],load:["overloaded"],
    video:["film"],compact:["resume"],compaction:["resume"],restart:["resume"],owner:["favio"],publish:["release"],classify:["judge"],duplicate:["dedup"]};
  const tok = s => String(s).toLowerCase().replace(/[“”"'’.,!?():;/]+/g, " ").split(/\s+/).filter(w => w && !STOP.has(w));
  function lev(a, b) {
    if (Math.abs(a.length - b.length) > 2) return 9;
    const d = Array.from({length:a.length + 1}, (_, i) => [i]);
    for (let j = 1; j <= b.length; j++) d[0][j] = j;
    for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++)
      d[i][j] = Math.min(d[i-1][j] + 1, d[i][j-1] + 1, d[i-1][j-1] + (a[i-1] === b[j-1] ? 0 : 1));
    return d[a.length][b.length];
  }
  RB.forEach(r => { r.corpus = [...new Set(tok(r.t + " " + r.keys.join(" ") + " " + r.tags))]; });
  function score(q) {
    const raw = tok(q); if (!raw.length) return [];
    const qs = raw.slice(); raw.forEach(w => (SYN[w] || []).forEach(x => qs.push(x)));
    const ql = String(q).toLowerCase().replace(/[“”"’]/g, "").trim();
    return RB.map(r => {
      let s = 0; const hit = new Set();
      raw.forEach((w, wi) => {
        const alts = [w].concat(SYN[w] || []);
        let best = 0, bw = "";
        alts.forEach(a => r.corpus.forEach(c => {
          let v = 0;
          if (c === a) v = 3;
          else if (a.length >= 3 && c.length >= 3 && (c.startsWith(a) || a.startsWith(c))) v = 2;
          else if (a.length >= 4 && c.length >= 4 && lev(a, c) <= (a.length >= 7 ? 2 : 1)) v = 1.5;
          if (a !== w) v *= .8;
          if (v > best) { best = v; bw = w; }
        }));
        s += best; if (best) hit.add(bw);
      });
      r.keys.forEach(k => { if (ql.includes(k)) s += 4 + k.split(" ").length; });
      return {r, s: s / Math.sqrt(raw.length), hit:[...hit]};
    }).filter(x => x.s >= 2).sort((a, b) => b.s - a.s);
  }
  const res = $("#fRes"), meta = $("#fMeta"), input = $("#fq"), chipsEl = $("#fChips");
  chipsEl.innerHTML = CHIPS.map(c => `<button type="button">${esc(c)}</button>`).join("");
  chipsEl.addEventListener("click", e => { const b = e.target.closest("button"); if (!b) return; input.value = b.textContent; run(); input.focus(); });
  const gateLi = g => `<li><i class="gm ${g[0]}" aria-hidden="true"></i><span><b style="color:var(--text);font-weight:600;text-transform:capitalize">${esc(g[0])}</b> · ${esc(g[1])}</span></li>`;
  function card(r, hit) {
    const why = hit && hit.length ? `<p class="why">Matched on ${hit.map(h => `<mark>${esc(h)}</mark>`).join(" ")}</p>` : `<p class="why">Runbook</p>`;
    const cmdHtml = c => c.tool
      ? `<div class="cmd tool"><span class="tk">${esc(c.tool)}</span><code>${esc(c.c)}</code></div>`
      : `<div class="cmd"><code class="${c.flag ? "flag" : ""}">${esc(c.c)}</code>${c.n ? `<span class="cn">${esc(c.n)}</span>` : ""}<button type="button" data-copy="${esc(c.c)}" aria-label="Copy command">Copy</button></div>`;
    const anyCmd = r.cmds.some(c => !c.tool), anyTool = r.cmds.some(c => c.tool);
    const cmdHead = anyCmd && anyTool ? "Commands and tools" : anyCmd ? "Commands" : "Tools";
    const cmds = r.cmds.length ? `<div class="kick" style="margin-top:16px">${cmdHead}</div><div class="cmds">${r.cmds.map(cmdHtml).join("")}</div>` : "";
    return `<article class="rb" data-id="${r.id}"><div class="rb-main"><div class="kick">Runbook</div><h3>${esc(r.t)}</h3>${why}
      <ol class="steps">${r.steps.map(s => `<li>${s}</li>`).join("")}</ol>${cmds}</div>
      <aside class="rb-side"><div><div class="side-k">Model</div><div class="side-model">${esc(r.model)}</div><p>${esc(r.why)}</p></div>
      <div><div class="side-k">Owner gates</div><ul class="gates-l">${r.gates.length ? r.gates.map(gateLi).join("") : `<li class="none">${esc(r.gnote || "None.")}</li>`}</ul></div>
      <div><div class="side-k">On this page</div><div class="seealso">${r.see.map(s => `<a href="${s[0]}">${esc(s[1])}</a>`).join("")}</div></div></aside></article>`;
  }
  function index(title) {
    return `<div class="find-meta" style="margin-top:4px">${esc(title)}</div><div class="rb-index">${RB.map(r => `<button type="button" data-open="${r.id}">${esc(r.t)}<small>${r.cmds.filter(c => !c.tool).length ? r.cmds.filter(c => !c.tool).length + " cmd" : ""}</small></button>`).join("")}</div>`;
  }
  let shown = null;
  function show(id, hit, others) {
    const r = RB.find(x => x.id === id); shown = id;
    res.innerHTML = card(r, hit) + (others && others.length ? `<div class="find-meta">Also close</div><div class="also">${others.map(o => `<button type="button" data-open="${o.r.id}">${esc(o.r.t)}<small>open</small></button>`).join("")}</div>` : "");
  }
  function run() {
    const q = input.value.trim();
    if (!q) { meta.textContent = `${RB.length} runbooks · type a situation, or pick one`; res.innerHTML = index("All runbooks"); shown = null; return; }
    const m = score(q);
    if (!m.length) { meta.textContent = "No close runbook"; res.innerHTML = `<div class="nomatch">Nothing close to “${esc(q)}”. Try other words, or open one below.</div>` + index("All runbooks"); return; }
    meta.textContent = m.length === 1 ? "1 match" : `${m.length} matches · best first`;
    show(m[0].r.id, m[0].hit, m.slice(1, 4));
  }
  let ft; input.addEventListener("input", () => { clearTimeout(ft); ft = setTimeout(run, 90); });
  input.addEventListener("keydown", e => { if (e.key === "Escape") { input.value = ""; run(); } });
  res.addEventListener("click", async e => {
    const o = e.target.closest("[data-open]"); if (o) { const r = RB.find(x => x.id === o.dataset.open); show(r.id, null, []); meta.textContent = "Opened from the list"; res.scrollIntoView({block:"nearest", behavior: reduced ? "auto" : "smooth"}); return; }
    const c = e.target.closest("[data-copy]");
    if (c) { try { await navigator.clipboard.writeText(c.dataset.copy); c.textContent = "Copied"; } catch (err) { c.textContent = "Select"; const code = c.parentElement.querySelector("code"); const rg = document.createRange(); rg.selectNodeContents(code); const s = getSelection(); s.removeAllRanges(); s.addRange(rg); } setTimeout(() => { c.textContent = "Copy"; }, 1400); }
  });
  const focusFind = () => { const top = $("#finder").getBoundingClientRect().top + window.scrollY - TOP - 13; window.scrollTo({top, behavior: reduced ? "auto" : "smooth"}); setTimeout(() => input.focus({preventScroll:true}), reduced ? 0 : 350); };
  const findBtn = $("#findBtn"); if (findBtn) findBtn.addEventListener("click", focusFind);
  document.addEventListener("keydown", e => {
    if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey) return;
    const t = e.target; if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
    e.preventDefault(); focusFind();
  });
  run();
})();

/* ================= EDITION 2 ================= each instrument starts near the viewport; nothing autoplays */
const lazy = (sel, fn) => { const el = $(sel); if (!el) return;
  if (!("IntersectionObserver" in window)) return fn(el);
  const io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) { io.disconnect(); fn(el); } }, {rootMargin: "400px 0px"});
  io.observe(el); };
const css = v => getComputedStyle($(".harness")).getPropertyValue(v).trim();
const pressOne = (btns, b) => btns.forEach(x => x.setAttribute("aria-pressed", x === b ? "true" : "false"));
const mmss = t => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, "0")}`;

/* one list, two views: the ledger rows live in the page (#ledgerData, also the no-JS text); the cards and the
   scars wall's edition 2 filter are drawn from them */
const LEDGER = [...document.querySelectorAll("#ledgerData > li")].filter(li => ["t", "r", "m", "w", "who", "c", "b"].every(c => li.querySelector("." + c))).map(li => { const f = c => li.querySelector("." + c).textContent;
  return {d:li.dataset.d, k:li.dataset.k.split(" "), l:li.dataset.l.split("|"), t:f("t").replace(/\.$/, ""), r:f("r"), m:f("m").replace(/\.$/, ""),
    s:[...li.querySelectorAll(".s li")].map(x => x.textContent), w:f("w"), who:f("who"), c:f("c"), b:f("b")}; });

(function edition() {
  const sw = $("#edSwitch"), root = $(".harness"); if (!sw) return;
  document.querySelectorAll(".harness section[data-ed]").forEach(sec => {
    const k = sec.dataset.ed, c = `<em class="ed-chip ${k}">${k === "new" ? "New" : "Updated"}</em>`;
    const no = sec.querySelector(".sec-no, .eyebrow"); if (no) no.insertAdjacentHTML("beforeend", c);
    const a = sec.id && $(`.index a[href="#${sec.id}"]`); if (a) { a.dataset.ed = k; a.insertAdjacentHTML("beforeend", c); }
  });
  sw.hidden = false;
  sw.addEventListener("click", () => { const on = sw.getAttribute("aria-checked") !== "true";
    sw.setAttribute("aria-checked", String(on)); root.classList.toggle("ed-diff", on); });
})();

lazy("#ledgerCards", el => {
  /* a practice per card: the rule and how to set it up on the front; the miss behind it on the back */
  el.innerHTML = LEDGER.map((r, i) => `<article class="lc"><div class="lc-in">
    <div class="lc-f"><div class="lc-n"><b>${String(i + 1).padStart(2, "0")}</b><span>Practice</span></div><h3>${esc(r.t)}</h3><p class="lc-r">${esc(r.r)}</p>
      <details class="lc-s" open><summary>Set it up</summary><ol>${r.s.map(x => `<li>${esc(x)}</li>`).join("")}</ol></details>
      <div class="lc-tags">${r.k.map(k => `<span class="tag ${k === "check" ? "amber" : "dim"}">${k}</span>`).join(" ")}</div></div>
    <div class="lc-b" id="lcb${i}"><div class="lc-n"><b>${String(i + 1).padStart(2, "0")}</b><span>${esc(r.d)}</span></div><h3>${esc(r.m)}</h3><p>${esc(r.w)}</p>
      <dl><div><dt>Noticed by</dt><dd>${esc(r.who)}</dd></div><div class="cost"><dt>What it cost</dt><dd>${esc(r.c)}</dd></div><div><dt>What it became</dt><dd>${esc(r.b)}</dd></div></dl>
      <a href="#scar-e2-${i + 1}" tabindex="-1">Its card on the scars wall</a></div></div>
    <button type="button" class="lc-btn" aria-expanded="false" aria-controls="lcb${i}">The miss behind it</button></article>`).join("");
  el.addEventListener("click", e => {
    const b = e.target.closest(".lc-btn"); if (!b) return;
    const card = b.closest(".lc"), on = b.getAttribute("aria-expanded") !== "true";
    b.setAttribute("aria-expanded", String(on)); card.classList.toggle("flip", on);
    b.textContent = on ? "Back to the practice" : "The miss behind it";
    card.querySelector(".lc-b a").tabIndex = on ? 0 : -1;
  });
  const n = LEDGER.filter(r => r.k.includes("check")).length, sum = $("#ledgerSum");
  const W = ["none","one","two","three","four","five","six"];
  if (sum) sum.textContent = `${W[n].replace(/^./, c => c.toUpperCase())} of the six became code. The other ${W[6 - n]} are written rules, which hold only while every session reads them; in edition 1, 22 of 41 rules had code behind them.`;
});

/* ---------- N1 · the verdict was for an earlier cut ---------- */
lazy("#vc", vc => {
  const FW = 1600, FH = 900, TR = {x:40, y:60, s:1.1};   /* the lanes panel's transform, film pixels */
  /* the text a render draws at time t, in the panel's units */
  const texts = (r, t) => { const k = Math.round(t * 10), o = [];
    if (k >= 455 && k <= 472) o.push({n:"label b", x:560, y:420, w:420, h:56, f:"500 40px", c:"rgba(170,184,196,.7)"});
    if (t >= 38) o.push(r === 7 ? {n:"LABEL A", x:560, y:180, w:300, h:72, f:"800 52px", c:"#ff7262"} : {n:"LABEL A", x:640, y:404, w:300, h:72, f:"800 52px", c:"#ff7262"});
    return o; };
  /* boxes through the transform; an overlap of more than 4 px both ways is a hit */
  const box = b => ({l:TR.x + b.x * TR.s, t:TR.y + b.y * TR.s, r:TR.x + (b.x + b.w) * TR.s, b:TR.y + (b.y + b.h) * TR.s, n:b.n});
  const test = (r, t) => { const B = texts(r, t).map(box), hits = [];
    for (let i = 0; i < B.length; i++) for (let j = i + 1; j < B.length; j++) {
      const ox = Math.min(B[i].r, B[j].r) - Math.max(B[i].l, B[j].l), oy = Math.min(B[i].b, B[j].b) - Math.max(B[i].t, B[j].t);
      if (ox > 4 && oy > 4) hits.push({a:B[i], b:B[j], ox, oy});
    } return {B, hits}; };
  const thumb = r => `<svg viewBox="0 0 160 90" aria-hidden="true"><rect width="160" height="90" class="th-bg"/><path d="M8 28h144M8 56h144" class="th-ln"/>
    <rect x="${r === 7 ? 62 : 70}" y="${r === 7 ? 24 : 47}" width="34" height="8" class="th-a"/><rect x="62" y="49" width="46" height="6" class="th-b"/>${r === 10 ? '<rect x="62" y="24" width="34" height="8" class="th-was"/>' : ""}</svg>`;
  vc.innerHTML = `<div class="vc-tl" role="group" aria-label="Renders of one film. Select final-7 or final-10 to load it into the player">
    <button type="button" class="vc-r" data-r="7" aria-pressed="true">${thumb(7)}<b>final-7</b><span class="stamp g">post it</span><small>critic round 2 judged this one</small></button>
    <div class="vc-r faint" aria-hidden="true"><b>final-8</b><small>a later render</small></div>
    <div class="vc-r faint fx" aria-hidden="true"><b>final-9</b><small>a later render; the critic’s fixes land in final-10</small></div>
    <button type="button" class="vc-r" data-r="10" aria-pressed="false">${thumb(10)}<b>final-10</b><span class="stamp ghost">post it</span><small><span class="tag">sent</span> verdict carried, not re-judged; the director checked its contact sheet and passed it too</small></button>
  </div>
  <div class="vc-pl"><canvas class="vc-cv" role="img"></canvas>
    <div class="vc-now" aria-live="polite"></div>
    <div class="vc-scr"><div class="vc-sl" role="slider" tabindex="0" aria-label="Time in the synthetic film" aria-valuemin="0" aria-valuemax="60">
      <div class="vc-track"><i class="vc-fill"></i><i class="vc-th"></i></div>
      <canvas class="vc-lane" aria-hidden="true"></canvas>
    </div><div class="vc-lk">the test, every 0.1 s, above<span>untested</span><span class="ok">no overlap</span><span class="hit">overlap</span></div></div>
    <div class="vc-ctl"><div><button class="btn" type="button" data-a="sweep">Sweep every 0.1 s</button> <button class="btn ghost" type="button" data-a="clear">Clear the lane</button></div><p class="vc-sw" aria-live="polite"></p>
      <p class="note">Dashed boxes are the text boxes the test measures, through the panel’s transform; red is where two overlap. Arrow keys move 0.1 s, Shift and an arrow 1 s.</p></div>
  </div>`;
  const cv = $(".vc-cv", vc), lane = $(".vc-lane", vc), sl = $(".vc-sl", vc), now = $(".vc-now", vc), swr = $(".vc-sw", vc);
  const rbtn = [...vc.querySelectorAll("button.vc-r")];
  const res = {7: new Int8Array(601), 10: new Int8Array(601)};
  let r = 7, k = 460, sweeping = 0;
  const fit = c => { const w = c.clientWidth, h = c.clientHeight, d = Math.min(2, window.devicePixelRatio || 1);
    if (c.width !== Math.round(w * d)) { c.width = Math.round(w * d); c.height = Math.round(h * d); } return d; };
  function film(t, T) {
    const d = fit(cv), x = cv.getContext("2d"), s = cv.width / FW;
    x.setTransform(s, 0, 0, s, 0, 0);
    x.fillStyle = "#0b1118"; x.fillRect(0, 0, FW, FH);
    x.strokeStyle = "rgba(120,170,200,.08)"; x.lineWidth = 1;
    for (let g = 0; g <= FW; g += 80) { x.beginPath(); x.moveTo(g, 0); x.lineTo(g, FH); x.stroke(); }
    x.font = "500 30px 'IBM Plex Mono',monospace"; x.fillStyle = "#81909c";
    x.fillText("SYNTHETIC FILM · DRAWN FOR THIS PAGE", 40, 44); x.textAlign = "right"; x.fillText(`final-${r} · ${mmss(t)}`, FW - 40, 44); x.textAlign = "left";
    x.save(); x.translate(TR.x, TR.y); x.scale(TR.s, TR.s);
    [[120, "lane 1"], [380, "lane 2"]].forEach(([y, n]) => { x.strokeStyle = "#34485b"; x.strokeRect(40, y, 1300, 200); x.fillStyle = "#81909c"; x.font = "500 28px 'IBM Plex Mono',monospace"; x.fillText(n, 56, y + 36); });
    x.strokeStyle = "#66d8ea"; x.lineWidth = 3; x.beginPath();
    for (let i = 0; i <= 260; i++) { const u = i / 260, y = 330 + Math.sin(u * 18 + t * 1.3) * 34 * Math.sin(u * 3.1 + .4) - 110; i ? x.lineTo(60 + u * 1260, y) : x.moveTo(60 + u * 1260, y); }
    x.stroke();
    texts(r, t).forEach(b => { x.font = `${b.f} 'IBM Plex Sans',sans-serif`; x.fillStyle = b.c; x.textBaseline = "middle";
      const m = x.measureText(b.n).width, sc = Math.min(1, (b.w - 16) / m); x.save(); x.translate(b.x + 8, b.y + b.h / 2); x.scale(sc, 1); x.fillText(b.n, 0, 0); x.restore(); });
    x.restore(); x.textBaseline = "alphabetic";
    T.B.forEach(b => { x.strokeStyle = "rgba(102,216,234,.85)"; x.setLineDash([8, 6]); x.lineWidth = 2; x.strokeRect(b.l, b.t, b.r - b.l, b.b - b.t); });
    x.setLineDash([]);
    T.hits.forEach(h => { const l = Math.max(h.a.l, h.b.l), tp = Math.max(h.a.t, h.b.t);
      x.fillStyle = "rgba(255,114,98,.35)"; x.fillRect(l, tp, h.ox, h.oy); x.strokeStyle = "#ff7262"; x.lineWidth = 3; x.strokeRect(l, tp, h.ox, h.oy); });
    x.fillStyle = "#223040"; x.fillRect(40, FH - 40, FW - 80, 6); x.fillStyle = "#ffb547"; x.fillRect(40, FH - 40, (FW - 80) * t / 60, 6);
  }
  function drawLane() {
    const d = fit(lane), x = lane.getContext("2d"), w = lane.width, h = lane.height, R = res[r], cw = w / 600;
    x.clearRect(0, 0, w, h); x.fillStyle = css("--bg-3"); x.fillRect(0, 0, w, h);
    const col = [null, css("--green"), css("--red")];
    for (let i = 0; i < 600; i++) if (R[i]) { x.globalAlpha = R[i] === 1 ? .45 : 1; x.fillStyle = col[R[i]]; x.fillRect(Math.floor(i * cw), 0, Math.floor((i + 1) * cw) - Math.floor(i * cw), h); }
    x.globalAlpha = 1; x.fillStyle = css("--amber"); x.fillRect(Math.round(k / 600 * w) - d, 0, 2 * d, h);
  }
  function set(nk, quiet) {
    k = Math.max(0, Math.min(600, Math.round(nk))); const t = k / 10, T = test(r, t);
    if (k < 600) res[r][k] = T.hits.length ? 2 : 1;
    film(t, T); drawLane();
    $(".vc-fill", vc).style.width = $(".vc-th", vc).style.left = (k / 6) + "%";
    sl.setAttribute("aria-valuenow", t.toFixed(1)); sl.setAttribute("aria-valuetext", `${t.toFixed(1)} seconds`);
    const msg = T.hits.length ? `${mmss(t)} · ${T.B.length} texts drawn · ${T.hits[0].b.n} over ${T.hits[0].a.n}: ${Math.round(T.hits[0].ox)} × ${Math.round(T.hits[0].oy)} px` : `${mmss(t)} · ${T.B.length === 1 ? "1 text" : T.B.length + " texts"} drawn · no overlap`;
    cv.setAttribute("aria-label", `Synthetic film, final-${r}, at ${msg}`);
    now.classList.toggle("hit", !!T.hits.length);
    if (!quiet) now.textContent = msg;
  }
  function summary() {
    const R = res[r], hit = []; for (let i = 0; i < 600; i++) if (R[i] === 2) hit.push(i);
    swr.textContent = hit.length ? `Sweep of final-${r}: overlap from ${mmss(hit[0] / 10)} to ${mmss(hit[hit.length - 1] / 10)}, ${hit.length} samples` : `Sweep of final-${r}: no overlap at any 0.1 s`;
  }
  function sweep() {
    if (sweeping) return; const back = k;
    if (reduced) { for (let i = 0; i < 600; i++) set(i, true); set(back); summary(); return; }
    let i = 0; sweeping = 1;
    const step = () => { for (let n = 0; n < 6 && i < 600; n++) set(i++, true); if (i < 600) requestAnimationFrame(step); else { sweeping = 0; set(back); summary(); } };
    requestAnimationFrame(step);
  }
  rbtn.forEach(b => b.addEventListener("click", () => { r = +b.dataset.r; pressOne(rbtn, b); swr.textContent = ""; set(k); }));
  vc.querySelector('[data-a="sweep"]').addEventListener("click", sweep);
  vc.querySelector('[data-a="clear"]').addEventListener("click", () => { res[r].fill(0); swr.textContent = ""; set(k); });
  const fromX = e => { const b = $(".vc-track", vc).getBoundingClientRect(); return (e.clientX - b.left) / b.width * 600; };
  sl.addEventListener("pointerdown", e => { sl.setPointerCapture(e.pointerId); sl.focus(); set(fromX(e)); });
  sl.addEventListener("pointermove", e => { if (sl.hasPointerCapture(e.pointerId)) set(fromX(e)); });
  sl.addEventListener("keydown", e => {
    const st = e.shiftKey ? 10 : 1, m = {ArrowRight:st, ArrowUp:st, ArrowLeft:-st, ArrowDown:-st, PageUp:10, PageDown:-10}[e.key];
    if (m) set(k + m); else if (e.key === "Home") set(0); else if (e.key === "End") set(600); else return;
    e.preventDefault();
  });
  let rz; window.addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => set(k, true), 150); });
  const mo = new MutationObserver(() => set(k, true)); mo.observe(document.documentElement, {attributes:true, attributeFilter:["data-theme"]});
  set(k);
});

/* ---------- N2 · what a compaction keeps ---------- */
lazy("#cmp", cmp => {
  const MAX = 13500, P = v => (v / MAX * 100).toFixed(2) + "%";
  const st = $("#cmpStage"), rd = $("#cmpRead"), btns = [...cmp.querySelectorAll(".cmp-bar .btn")];
  const LINES = {
    old: [["p", "practices · first lines"], ["p2", "practices · later lines"], ["s", "this session’s state: what it was doing, what it promised"]],
    new: [["c", "rules card · first line: read the full practices before anything else"], ["s", "this session’s own state file, matched by its session id"]]
  };
  const READ = {
    old: "Old hook, reconstructed from the files: it would have printed 12,957 characters, and only a 2,000-character preview arrives. The session’s own state was printed last, so it was the first thing lost. This happened on 2 of the director’s 9 compactions under the old hook.",
    new: "New hook: a short rules card and this session’s own state file, under the line. Both arrive whole.",
    after: "After the compaction the session sits idle: a compaction doesn’t start a turn. A message from the director wakes it, and it resumes from its state file."
  };
  function show(s) {
    const o = s === "old", a = s === "after";
    st.innerHTML = `<div class="cmp-out${a ? " dim" : ""}"><div class="cmp-lab"><span>hook output</span><span class="num">${o ? "<b>12,957</b> to print · <b>2,000</b> arrived (reconstructed)" : "arrived whole"}</span></div>
      <div class="cmp-track">${o ? `<div class="seg p" style="width:${P(8770)}"><span>practices</span></div><div class="seg s" style="left:${P(8770)};width:${P(4187)}"><span>state</span></div>
        <div class="cut" style="right:${P(MAX - 12957)};--w:${P(10957)}"></div><i class="mk pv" style="left:${P(2000)}"><span>preview</span></i>`
        : `<div class="seg c" style="width:${P(2400)}"><span>card</span></div><div class="seg s" style="left:${P(2400)};width:${P(4300)}"><span>state file</span></div><i class="mk bd" style="left:${P(9000)}"><span>budget</span></i>`}
        <i class="mk cap" style="left:${P(10000)}"><span>cap</span></i></div></div>
      <div class="cmp-sess${a ? " idle" : ""}"><div class="cmp-sh"><span>the session, after a compaction</span><span class="state">${a ? "idle" : "reading"}</span></div>
        ${a ? `<p class="cmp-idle">idle: a compaction doesn’t start a turn</p><div class="env"><i aria-hidden="true"></i>from the director: resume from your state file</div><p class="cmp-wake">working again, from its own state file</p>`
        : `<ol class="${o ? "old" : ""}">${LINES[o ? "old" : "new"].map(([c, t], i) => `<li class="${c}" style="--d:${o ? [.9, .45, 0][i] : 0}s">${esc(t)}</li>`).join("")}</ol>${o ? `<p class="cmp-pv">output saved to a file · the session gets a preview of the first 2,000 characters</p>` : ""}`}
      </div>`;
    rd.textContent = READ[s];
    requestAnimationFrame(() => requestAnimationFrame(() => { st.classList.add("go");
      if (a) setTimeout(() => { const e = $(".cmp-sess", st); if (e) { e.classList.remove("idle"); $(".state", e).textContent = "working"; } }, reduced ? 0 : 1300); }));
    st.classList.remove("go");
  }
  btns.forEach(b => b.addEventListener("click", () => { pressOne(btns, b); show(b.dataset.s); }));
  show("old");
});

/* ---------- N3 · one session became many ---------- */
lazy("#lns", root => {
  const svg = $("#lnsSvg"), panel = $("#lnsPanel"), K = $("#lnsK"), T = $("#lnsT"), playB = $("#lnsPlay");
  const vbtn = [...root.querySelectorAll("[data-v]")];
  const LN = [["release code", "The 0.4.6 pull requests, and the checks that go into showtime."],
    ["reviews", "The reviewer session. It reads every pull request, and its verdict is part of the merge gate."],
    ["films", "Films made with showtime. Each aspect is checked as its own film."],
    ["experiment", "A measured experiment and its write-up."],
    ["this article", "This page and the article that goes with it."], ["", "A lane not named here."], ["", "A lane not named here."]];
  const ENV = [["dir", 5, "a brief, from the director to a new lane"], [0, 1, "a new PR head, sent to the reviewer"],
    ["dir", 2, "resume from your state file, after a compaction"], [1, 0, "a verdict back to the lane"]];
  let view = "many", playing = false, clock = 0, last = 0, vis = true, blocks = 13, fill = .18, sel = -1, geo;
  const wide = () => root.clientWidth >= 700;
  function layout() {
    if (wide()) { const W = 1000; return {W, H:420, D:{x:380, y:20, w:240, h:110}, L:LN.map((_, i) => ({x:6 + i * 141.6, y:300, w:130, h:84})),
      edge:(d, l) => `M${d.x + d.w / 2},${d.y + d.h} C${d.x + d.w / 2},${(d.y + d.h + l.y) / 2 + 20} ${l.x + l.w / 2},${(d.y + d.h + l.y) / 2 - 20} ${l.x + l.w / 2},${l.y}`}; }
    return {W:360, H:640, D:{x:60, y:8, w:240, h:110}, L:LN.map((_, i) => ({x:56, y:150 + i * 68, w:296, h:56})),
      edge:(d, l) => `M${d.x},${d.y + d.h / 2} H26 V${l.y + l.h / 2} H${l.x}`};
  }
  function draw() {
    const g = geo = layout(); svg.setAttribute("viewBox", `0 0 ${g.W} ${g.H}`); svg.classList.toggle("tall", !wide());
    let h = `<g class="ln-edges">${g.L.map((l, i) => `<path class="edge" id="lnE${i}" d="${g.edge(g.D, l)}"/>`).join("")}</g>`;
    h += `<g class="node k-amber${sel === -1 ? " sel" : ""}" data-i="-1" tabindex="0" role="button" aria-label="The director: show what it keeps"><rect class="box" x="${g.D.x}" y="${g.D.y}" width="${g.D.w}" height="${g.D.h}"/><rect class="bar" x="${g.D.x}" y="${g.D.y}" width="4" height="${g.D.h}"/>
      <text class="nl" x="${g.D.x + 16}" y="${g.D.y + 26}">director</text><text class="ns" x="${g.D.x + 16}" y="${g.D.y + 44}">THE ONE LIST · MERGES · FAVIO</text>
      <rect class="gauge" x="${g.D.x + 16}" y="${g.D.y + 58}" width="${g.D.w - 32}" height="10"/><rect class="gfill" id="lnsG" x="${g.D.x + 16}" y="${g.D.y + 58}" width="${(g.D.w - 32) * fill}" height="10"/>
      <text class="ns" x="${g.D.x + 16}" y="${g.D.y + 92}" id="lnsB">RESUME BLOCKS WRITTEN: ${blocks}</text></g>`;
    h += g.L.map((l, i) => `<g class="node lane${LN[i][0] ? "" : " k-dim un"}${sel === i ? " sel" : ""}" data-i="${i}" tabindex="0" role="button" aria-label="${LN[i][0] ? LN[i][0] : "a lane not named here"}: show the shape of its state file" style="--i:${i}">
      <rect class="box" x="${l.x}" y="${l.y}" width="${l.w}" height="${l.h}"/><rect class="bar" x="${l.x}" y="${l.y}" width="4" height="${l.h}"/>
      <text class="nl" x="${l.x + 14}" y="${l.y + (wide() ? 32 : 25)}">${LN[i][0] || "not named"}</text><text class="ns" x="${l.x + 14}" y="${l.y + (wide() ? 54 : 44)}">STATE FILE</text></g>`).join("");
    h += `<g id="lnsEnv" class="env-g" opacity="0"><rect x="-10" y="-7" width="20" height="14" rx="1"/><path d="M-10,-7 L0,1 L10,-7"/></g>`;
    svg.innerHTML = h; svg.classList.toggle("one", view === "one");
  }
  function info(i) {
    sel = i; svg.querySelectorAll(".node").forEach(n => n.classList.toggle("sel", +n.dataset.i === i));
    const nm = i < 0 ? "director" : LN[i][0] || "a lane not named here";
    panel.innerHTML = `<h3>${esc(nm)}</h3><div class="sub">${i < 0 ? "the director session" : "a lane session · the shape of its state file"}</div>
      <p>${i < 0 ? "Keeps the one list of what is open, merges, and talks to Favio. From 8 Oct until the work split into lanes on 15 Oct it was compacted 19 times, and before at least 12 of those it wrote a resume block into its state file." : esc(LN[i][1])}</p>
      <pre class="sf">${i < 0 ? "# RESUME HERE (written before a compaction)\nRead this, then the open list.\n\n## Waiting on the owner\n- &lt;item&gt;: &lt;the decision needed&gt;\n\n## Running\n- &lt;lane&gt;: &lt;how you’ll know it’s done&gt;"
        : "# the lane’s state file\ncwd:     &lt;its working folder&gt;\nsession: &lt;its session id&gt;\nupdated: &lt;date, time&gt;\n\n## Now\n- &lt;what it is doing; how the director\n  will know it is done&gt;\n\n## Promises\n- &lt;what it promised, and to whom&gt;"}</pre>
      <p class="note">Values are placeholders. The start-up hook finds this file by the session’s id and puts it in context after every compaction.</p>`;
  }
  function setView(v) { view = v; pressOne(vbtn, vbtn.find(b => b.dataset.v === v)); svg.classList.toggle("one", v === "one");
    svg.setAttribute("viewBox", `0 0 ${geo.W} ${v === "one" && !wide() ? 130 : geo.H}`);
    K.textContent = v === "one" ? "one session did almost everything" : "seven lanes today; two not named";
    T.textContent = v === "one" ? "planning, merging, releases, articles, films: and 19 compactions before the lane split on 15 Oct" : reduced || !playing ? "messages: a brief · a new PR head to the reviewer · resume from your state file · a verdict back" : ""; }
  function gauge(f, b) { fill = f; blocks = b; const G = $("#lnsG"), B = $("#lnsB"); if (G) G.setAttribute("width", (geo.D.w - 32) * f); if (B) B.textContent = `RESUME BLOCKS WRITTEN: ${b}`; }
  function setPlay(v) { playing = v && !reduced; playB.setAttribute("aria-pressed", String(playing)); playB.textContent = playing ? "Pause" : "Play";
    if (v && reduced) { gauge(.18, 13); setView("many"); }
    if (playing) { if (clock === 0) { gauge(0, 0); setView("one"); } last = performance.now(); requestAnimationFrame(tick); } }
  function envAt(e, u) {   /* lane to lane goes through the director */
    const seg = [], [a, b] = e; if (a !== "dir") seg.push([a, true]); seg.push([b, false]);
    const n = seg.length, j = Math.min(n - 1, Math.floor(u * n)), v = u * n - j, p = $("#lnE" + seg[j][0]), L = p.getTotalLength();
    return p.getPointAtLength(seg[j][1] ? L * (1 - v) : L * v);
  }
  function tick(t) {
    if (!playing) return;
    const dt = Math.min(.1, (t - last) / 1000); last = t; if (vis) clock += dt;
    const E = $("#lnsEnv");
    if (clock < 6.5) { const c = clock / .5, f = c % 1; gauge(f < .8 ? .15 + f / .8 * .85 : 1 - (f - .8) / .2 * .82, Math.min(13, Math.floor(c + .2))); }
    else if (view === "one") { gauge(.18, 13); setView("many"); T.textContent = ""; }
    else if (clock > 7.5) { const q = (clock - 7.5) / 1.8, e = ENV[Math.floor(q) % ENV.length], u = q % 1;
      const pt = envAt(e, Math.min(1, u / .85)); E.setAttribute("transform", `translate(${pt.x},${pt.y})`); E.setAttribute("opacity", u > .92 ? 0 : 1);
      T.textContent = e[2]; }
    requestAnimationFrame(tick);
  }
  vbtn.forEach(b => b.addEventListener("click", () => { setPlay(false); clock = 0; gauge(b.dataset.v === "one" ? .7 : .18, 13); setView(b.dataset.v); const E = $("#lnsEnv"); if (E) E.setAttribute("opacity", 0); }));
  playB.addEventListener("click", () => setPlay(!playing));
  const act = e => { const n = e.target.closest(".node"); if (n) info(+n.dataset.i); };
  svg.addEventListener("click", act);
  svg.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); act(e); } });
  new IntersectionObserver(es => { vis = es[0].isIntersecting; }).observe(svg);
  let rz, ww = wide(); window.addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => { if (wide() !== ww) { ww = wide(); draw(); } }, 150); });
  draw(); setView("many"); info(-1);
});

/* ---------- N5 · three days, measured ---------- */
lazy("#ttm", () => {
  /* merged PRs, in merge order: minutes after 9 Oct 00:00 UTC, hours open × 1000, added lines */
  const RAW = "40,830,165;308,4650,114;308,4658,82;368,586,43;406,1011,46;406,1377,18;446,7013,590;465,1677,350;468,2,13;530,2804,113;567,3929,213;734,5936,22;759,5206,313;838,3202,385;897,5076,123;941,5092,211;1024,2359,131;1024,2551,26;1024,2743,52;1049,117,11;1052,4693,124;1058,3406,38;1354,2708,28;1367,2868,66;1445,4149,82;1449,4192,83;1573,6221,93;1718,8638,223;1833,9456,37;1858,9123,56;2015,12250,1552;2016,6291,258;2017,3468,642;2017,6184,647;2660,7055,285;2666,2502,39;2778,1084,99;2858,1139,9;2933,897,89;3035,976,20;3243,1024,108;3419,3124,265;3707,446,15;4078,2794,128;4236,825,12;4285,290,23;4324,425,71;4722,4358,2490;4782,852,4;4886,5651,3316;5464,12934,4076;5487,3375,2870;5678,13081,510;5703,7195,285;5727,16334,158;5842,7757,2868;5876,3510,253;5989,3041,897;6063,741,6232;6203,677,19;7048,7866,12250;7048,10852,4087;7849,1596,94;7852,1649,39;7971,3261,1175;8180,7110,969;8242,2038,340;8306,882,65;8325,321,137;8335,221,19;8363,174,132;8392,49,16;8420,79,2;8458,81,3;8554,680,12;9197,2572,264;9234,2231,344;9255,3303,69;9263,998,106;9323,712,173;9359,1309,78;9547,1805,651;9702,1335,162;9811,1693,68;9824,1498,691;9834,3669,151;9879,2924,335;9911,3471,194;9928,1555,135;9978,994,35;10114,3178,776;10162,478,16;10276,627,161;10326,350,49;10348,215,36;10535,255,3;10682,1280,99;10846,890,170;10905,210,62";
  const ART = 5383.35, END = 11160, D0 = Date.UTC(2026, 9, 9);
  const PR = RAW.split(";").map(s => { const [m, h, a] = s.split(",").map(Number); return {m, h:h / 1000, a, since:m >= ART}; });
  const RULES = [[ART, "first article"], [6761, "0.4.3"], [7045, "0.4.4"], [8857, "0.4.5"], [10995, "0.4.6"]];
  const plot = $("#ttmPlot"), read = $("#ttmRead"), cmpB = $("#ttmCmp");
  const when = m => { const d = new Date(D0 + m * 60000); return `${d.getUTCDate()} Oct ${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`; };
  const hrs = h => h < 1 / 60 ? "under a minute" : h < 1 ? `${Math.round(h * 60)} min` : `${h.toFixed(1)} h`;
  const say = p => `Merged ${when(p.m)} UTC · open ${hrs(p.h)} · ${p.a.toLocaleString("en-US")} added lines${p.since ? "" : " · first four days"}`;
  $("#ttmRows").innerHTML = PR.slice().sort((a, b) => a.m - b.m).map(p => `<tr${p.since ? "" : ' class="pre"'}><td class="n">${when(p.m)}</td><td class="n">${p.h.toFixed(2)}</td><td class="n">${p.a.toLocaleString("en-US")}</td></tr>`).join("");
  let cmp = plot.clientWidth >= 640, cur = -1, vis = [], X, Y, M;
  function draw() {
    const w = plot.clientWidth, h = w < 560 ? 300 : 360; M = {l:50, r:12, t:40, b:30};
    const x0 = cmp ? 0 : ART - 360, lo = Math.log(1 / 60), hi = Math.log(24);
    X = m => M.l + (m - x0) / (END - x0) * (w - M.l - M.r);
    Y = v => M.t + (1 - (Math.log(Math.max(1 / 60, v)) - lo) / (hi - lo)) * (h - M.t - M.b);
    vis = PR.filter(p => cmp || p.since).sort((a, b) => a.m - b.m);
    let s = `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true">`;
    [[1 / 60, "1 min"], [1 / 6, "10 min"], [1, "1 h"], [10, "10 h"]].forEach(([v, l]) => { s += `<line class="gy" x1="${M.l}" x2="${w - M.r}" y1="${Y(v)}" y2="${Y(v)}"/><text class="tx" x="${M.l - 6}" y="${Y(v) + 4}" text-anchor="end">${l}</text>`; });
    for (let d = Math.ceil(x0 / 1440); d * 1440 <= END; d++) { const x = X(d * 1440); if (x < M.l) continue;
      s += `<line class="gx" x1="${x}" x2="${x}" y1="${M.t}" y2="${h - M.b}"/>`;
      if (X(d * 1440 + 720) < w - M.r) s += `<text class="tx" x="${X(d * 1440 + 720)}" y="${h - 10}" text-anchor="middle">${9 + d} Oct</text>`; }
    RULES.forEach(([m, l], i) => { const x = X(m), up = i ? 6 : 22; if (x < M.l) return; s += `<line class="rule${i ? "" : " art"}" x1="${x}" x2="${x}" y1="${M.t - up + 2}" y2="${h - M.b}"/><text class="rl" x="${i === 1 || i === RULES.length - 1 ? x - 3 : x + 3}" y="${M.t - up}"${i === 1 || i === RULES.length - 1 ? ' text-anchor="end"' : ""}>${l}</text>`; });
    [[0, ART, 3.0, "median 3.0 h"], [ART, END, 1.56, "median 1.6 h"]].forEach(([a, b, v, l], i) => { if (!cmp && !i) return;
      s += `<line class="med${i ? "" : " pre"}" x1="${Math.max(M.l, X(a))}" x2="${X(b)}" y1="${Y(v)}" y2="${Y(v)}"/><text class="ml" x="${Math.max(M.l, X(a)) + 5}" y="${Y(v) - 5}">${l}</text>`; });
    vis.slice().sort((a, b) => b.a - a.a).forEach(p => { const r = Math.max(2.5, Math.sqrt(Math.min(p.a, 4000) / 4000) * (w < 560 ? 10 : 14));
      s += `<circle class="dt${p.since ? "" : " pre"}" cx="${X(p.m)}" cy="${Y(p.h)}" r="${r}"/>`; });
    s += `<circle class="hl" r="0" cx="0" cy="0"/></svg>`;
    plot.innerHTML = s; pick(cur, true);
  }
  function pick(i, quiet) {
    cur = i; const c = $(".hl", plot); if (!c) return;
    if (i < 0 || !vis[i]) { c.setAttribute("r", 0); if (!quiet) read.textContent = ""; return; }
    const p = vis[i]; c.setAttribute("cx", X(p.m)); c.setAttribute("cy", Y(p.h)); c.setAttribute("r", 9);
    read.textContent = say(p);
  }
  read.textContent = "Hover or tap a dot, or focus the chart and use the arrow keys.";
  const near = e => { const b = plot.getBoundingClientRect(), x = e.clientX - b.left, y = e.clientY - b.top; let best = -1, bd = 900;
    vis.forEach((p, i) => { const d = (X(p.m) - x) ** 2 + (Y(p.h) - y) ** 2; if (d < bd) { bd = d; best = i; } }); return best; };
  plot.addEventListener("pointermove", e => { const i = near(e); if (i >= 0 && i !== cur) pick(i); });
  plot.addEventListener("pointerdown", e => { const i = near(e); if (i >= 0) pick(i); });
  plot.addEventListener("keydown", e => { const m = {ArrowRight:1, ArrowUp:1, ArrowLeft:-1, ArrowDown:-1}[e.key]; if (!m) return; e.preventDefault();
    pick(cur < 0 ? (m > 0 ? 0 : vis.length - 1) : (cur + m + vis.length) % vis.length); });
  cmpB.setAttribute("aria-pressed", String(cmp));
  cmpB.addEventListener("click", () => { const p = vis[cur]; cmp = !cmp; cmpB.setAttribute("aria-pressed", String(cmp)); draw(); cur = p ? vis.indexOf(p) : -1; pick(cur, true); });
  let rz, lw = plot.clientWidth; window.addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => { if (plot.clientWidth !== lw) { lw = plot.clientWidth; draw(); } }, 150); });
  draw();
  const wf = $("#waffle"); if (wf) wf.innerHTML = Array.from({length:181}, (_, i) => `<i class="${i < 137 ? "y" : i < 177 ? "c" : "n"}"></i>`).join("");
});

/* ================= 13 SCARS WALL ================= */
(function scars() {
  const AREAS = [["all","All"],["e2","New in edition 2"],["devin","Devin"],["tests","Tests & merges"],["films","Films"],["ops","Ops & state"]];
  const S = [
    {a:"tests", d:"11 Oct", t:"The tolerance we almost loosened",
     w:"An ARM Linux run failed a poster-colour test at 0.754 against a 0.75 tolerance. The first fix raised the tolerance.",
     c:"One PR amended while the release waited.",
     r:"Root cause before tolerance: ffmpeg’s gradient source was randomly seeded, so the seed is fixed now, and a mutant fails every run.", l:["the test","the Mac review"], go:"#day"},
    {a:"tests", d:"11 Oct", t:"A CI tweak that could lie",
     w:"A change let the nightly run take a list of tests. Devin found that a narrowed manual run could then count as a full run and close the issue that tracks a failing nightly.",
     c:"Caught in review, before the merge; one fix round.",
     r:"Only a full run, with no system or test filter, can close that issue; a guard test proves it.", l:["the CI workflow","a guard test"], go:"#day"},
    {a:"tests", d:"11 Oct", t:"A write race only Windows saw",
     w:"Three audio mixes running in parallel all replaced one report file. Windows refuses to replace a file another process holds; macOS and Linux never complained.",
     c:"A red end-to-end run on release day, a fix PR and three Devin re-checks.",
     r:"The write retries the replace for up to 2 s, as the run records already did; a test and a mutant prove it.", l:["showtime’s write helper","a test"], go:"#day"},
    {a:"tests", d:"11 Oct", t:"Two MERGEs, one red Linux test",
     w:"Devin and the Mac review both said MERGE on a feature PR. A full Linux suite on a cloud machine then failed a test neither had run: a new template lacked a file the motion test expects.",
     c:"The merge was held.",
     r:"The merge waits for the full Linux suite, even after two MERGE verdicts.", l:["the Mac review brief","the day log"], go:"#day"},
    {a:"tests", d:"11 Oct", t:"A cancel that lost the evidence",
     w:"The Intel full tier hit its 180-minute cap at file 77 of 84 and was cancelled. The showreel test had failed after 1,167 s, and its details went with the cancel.",
     c:"About three hours of Intel CI, and the failure’s details.",
     r:"Diagnose before re-running: the failing test runs alone first (it passed in 536 s, so load was the cause), and the cap is 300 minutes.", l:["the CI workflow","the day log"], go:"#day"},
    {a:"ops", d:"11 Oct", t:"A watchdog that read a symlink",
     w:"The watchdog judged a stuck agent by the age of its output file. That file is a symlink, so it read the link’s age, not the log’s.",
     c:"Not recorded.",
     r:"The watchdog follows the link (stat -L), and its test uses a symlinked log.", l:["the watchdog","its test"], go:"#lessons"},
    {a:"ops", d:"9 Oct", t:"A clock an hour off",
     w:"A python3 with a stale copy of the time-zone data had the local zone an hour off. Anything timed by it would have run an hour early.",
     c:"Caught in a Mac review before it fired: three time-zone tests failed under that python3.",
     r:"Read the OS zone database; 171 of 171 tests pass under the default python3.", l:["the day log"], go:"#day"},
    {a:"films", d:"9 Oct", t:"A flag that ate the prompt",
     w:"<code>claude -p … --disallowedTools &lt;list&gt;</code> takes a list: placed before the prompt, it swallowed it. A short film started with no instructions.",
     c:"A blind film run; the film was relaunched after the fix.",
     r:"The option goes first, with a regression test.", l:["the film command","a regression test"], go:"#films"},
    {a:"devin", d:"9 Oct", t:"A resume that reached the wrong Devin",
     w:"<code>devin --cloud -c</code> continues the account’s most recent cloud session, not the folder’s. A follow-up after a data-toy review landed on the reviewer.",
     c:"The reviewer applied its own fixes, so the toy review was no longer independent; Fable’s claims review became the final independent check.",
     r:"Send every builder follow-up first; start an independent reviewer last, as a new session without -c.", l:["Devin notes","the send script"], go:"#venues"},
    {a:"tests", d:"9 Oct", t:"Heavy tests under load",
     w:"With three heavy files at once on the Mac, test_render and test_audio hit the 900 s timeout. Load reached 155 with a final render, a film build and test reviews together.",
     c:"False failures and re-runs: test_render passed alone in 760 s; a test_looks byte diff under three-way load had 0 changed pixels.",
     r:"Re-run heavy files alone with <code>--timeout 2400</code>; send Mac reviews through one queue worker.", l:["toolbox notes"], go:"#venues"},
    {a:"films", d:"9 Oct", t:"A source behind a 403",
     w:"On 9 Oct the first Haiku pass of a lab’s pre-research failed: WebFetch got a 403 from the primary source.",
     c:"A failed research pass, rerun on Sonnet with curl.",
     r:"Verify primary texts in a real browser, or curl with a browser User-Agent.", l:["lab notes","fact-checking notes"], go:"#films"},
    {a:"tests", d:"9 Oct", t:"A waiter that waited on itself",
     w:"Workers waiting for each other’s test runs used <code>pgrep -f run_all.py</code>, which also matched the other waiters’ command lines, so every waiter ended up waiting on the others.",
     c:"A review starved for 40 minutes.",
     r:"Match real python runs only; better, run Mac reviews through one queue worker.", l:["the shared memory repo"], go:"#shipping"},
    {a:"tests", d:"9 Oct", t:"One merge broke main",
     w:"A PR added a 15th eval case; main’s scoreboard test still expected 14. The Mac review of that PR had missed that test.",
     c:"A red test on main, fixed on main.",
     r:"Mac reviews also run <code>run_all --changed</code> on the branch merged with main.", l:["toolbox notes"], go:"#shipping"},
    {a:"tests", d:"9 Oct", t:"Tested on Linux only",
     w:"An ffmpeg audio fix tested only on Linux was 11–21 ms off on macOS.",
     c:"Another Devin round for a macOS fix, then a second Mac review, before it could merge.",
     r:"A Mac review before any merge.", l:["toolbox notes","the shipping gates"], go:"#shipping"},
    {a:"films", d:"9 Oct", t:"Crew stopped mid-task",
     w:"Turn caps stopped the scriptwriter, the storyboard artist and the sound designer mid-task.",
     c:"Interrupted crew jobs.",
     r:"Resume, don’t restart. #42 raises the scriptwriter’s cap to 50 and the storyboard artist’s to 80.", l:["the showtime crew","issue #42"], go:"#routing"},
    {a:"films", d:"9 Oct", t:"Footage that wasn’t what it seemed",
     w:"A news clip held wire footage, not public domain, and a line we meant to use turned out to be said by a different speaker.",
     c:"The clip was unusable; the film cut a short excerpt from a CC BY 3.0 clip instead.",
     r:"A rights check before a clip is used, and a speaker check before cutting.", l:["the lab’s footage step"], go:"#films"},
    {a:"tests", d:"9 Oct", t:"An eval that passed by default",
     w:"The footage-missing-take case passed without showtime too: prompt-only takes did not discriminate (with 3/3, without 3/3).",
     c:"A paid eval run on a case that measured nothing.",
     r:"Scaffold real takes into the case: with 3/3, without 0/3.", l:["eval notes"], go:"#quality"},
    {a:"ops", d:"8 Oct", t:"Actions on private repos",
     w:"Pushing working code to the private repos ran the full Mac, Windows and Linux CI on every push and PR.",
     c:"The free private minutes went in hours: $3.88.",
     r:"Actions are off on the private repos; PR tests run locally and on Devin; the free public CI runs at release.", l:["tracker notes"], go:"#shipping"},
    {a:"devin", d:"3–5 Oct", t:"Messages that never left",
     w:"A message typed into a busy Devin session queues until its tool call ends; after a session finishes, a sent line can sit in the input box.",
     c:"A direction sat unread for over an hour (3 Oct); a fix note for ~25 min (4 Oct); an answer until Favio noticed (5 Oct).",
     r:"After every send, read the pane back and press Enter again if needed.", l:["Devin notes"], go:"#venues"},
    {a:"ops", d:"27 Sep", t:"State in /tmp",
     w:"A power outage wiped the /tmp scratch.",
     c:"Whatever state lived there.",
     r:"Never keep important state in /tmp. OPEN.md, STATE.md, PLAN.md and the day log hold it.", l:["OPEN.md","the shared memory repo"], go:"#day"},
    {a:"films", d:"29 Sep", t:"A headline that slid off-frame",
     w:"Favio rejected the v0.2.0 launch-video proof: the 9:16 cut off terminal commands, and in 16:9 the camera slid the headline off-frame.",
     c:"A rejected proof, and his question whether we were taking enough screenshots and checking the visuals at all.",
     r:"2 fps contact sheets of every delivered aspect, looked at before anything is sent.", l:["delivery notes"], go:"#films"},
    {a:"films", d:"7 Oct", t:"The bell that grated",
     w:"The 0.4.1 showreel’s visuals landed, but Favio rejected the music: the bell sounds were odd and grating.",
     c:"A music pick and a re-mix of the finals.",
     r:"Audition 3–4 tracks before cutting a reel to one.", l:["the owner’s working style"], go:"#films"},
    {a:"films", d:"7 Oct", t:"Almost inaudible on a phone",
     w:"The showreel mix lived in the bass: above 300 Hz it sat at −27.6 LUFS, against −16 to −20 for posted films. Favio could barely hear it.",
     c:"The mix was redone.",
     r:"qa checks speaker loudness, and the mixer has a speaker-safe step (0.4.1).", l:["showtime qa","STATE.md, 7 Oct"], go:"#films"},
    {a:"films", d:"8–9 Oct", t:"Nothing behind the painting",
     w:"A 2.5D depth parallax on a painting had nothing behind it when the camera moved.",
     c:"A weak prototype.",
     r:"A real 3D world in code, the print projected onto it, then ink.", l:["toolbox notes"], go:"#films"},
    {a:"ops", d:"8 Oct", t:"Routing drifted back to Opus",
     w:"In long sessions, sub-agents drifted back to the main model. Favio noticed and pointed out that the routing had been forgotten.",
     c:"Not recorded.",
     r:"A permanent agent definition per tier (Haiku, Sonnet, Fable), and a model picked for every sub-agent.", l:["global instructions","model-routing notes"], go:"#routing"},
    {a:"ops", d:"6–7 Oct", t:"Nightly red, unseen",
     w:"Public nightly CI failed on 6 and 7 Oct (windows-2022, macos-15-intel), and nobody saw it.",
     c:"Two red nights.",
     r:"A nightly job opens or updates one <code>ci: nightly</code> issue on failure and closes it when green.", l:["tracker notes"], go:"#shipping"},
    {a:"ops", d:"8 Oct", t:"A shared watcher swallowed a PR",
     w:"The shared PR watcher keeps one state file. A run from another session took in a PR update the review session should have reviewed.",
     c:"That update skipped its first-pass review.",
     r:"Only the review session runs the watcher.", l:["session notes"], go:"#shipping"},
    {a:"ops", d:"9 Oct", t:"Favio as the switchboard",
     w:"Favio was relaying messages between the working sessions by hand, going back and forth between them.",
     c:"His time, at about 01:00.",
     r:"The main session reads and messages the other sessions itself; only approvals go to Favio.", l:["session notes"], go:"#routing"},
    {a:"ops", d:"8 Oct", t:"Files Favio couldn’t open",
     w:"Files sent from a working folder showed up broken in the app, which said they did not exist.",
     c:"Deliverables he couldn’t open.",
     r:"Copy to the delivery folder the app can open first; phone videos ≤30 MB; HTML as a link.", l:["delivery notes"], go:"#finder"}
  ];
  /* edition 2, 16 Oct: four misses from the day after the six practices */
  const NEW16 = [
    {t:"A failed job read as still running",
     w:"A macOS test job on a release pull request had failed: two tests ran into their 900 s limit. The CI summary showed that job with no result yet, the status line read it as still running, and the report said nothing new had failed. Noticed by Favio.",
     c:"A failed release job went unreported until Favio asked. Its log led to a real bug: a page check could crawl for half an hour or more once a page stopped answering.",
     r:"Read each job’s own result, not the summary, and open the log of any job that did not succeed. In 0.4.6, a page check whose page stops answering ends with an error.", l:["the practices", "the CI checks"]},
    {t:"A PDF checked on page 1",
     w:"A paper’s final PDF went out after a look at its first page. It had a half-empty page with one column, figure pages scattered through the text and no References heading. The next build put figures after the references, under no heading. Noticed by Favio, twice.",
     c:"Two rejected builds of a paper, before it was published.",
     r:"A contact sheet of every page and a full-size look at each, then a reader’s check: every page sits under a heading the reader has seen, in the order one publisher’s own author guide gives.", l:["the practices"]},
    {t:"A speed-up that shortened the wait",
     w:"A setting that makes a deadline test run faster also shortened the time it allowed to open the page. The test passed on a quiet machine and timed out opening the page on a busy one. Noticed by the cloud reviewer.",
     c:"A release fix waited while the cause was found.",
     r:"Opening the page has its own time limit, apart from the speed-up, and the test runs on a quiet and a loaded machine before it merges. It now passes on both.", l:["the test helper", "the practices"]},
    {t:"A pull request that read like someone else wrote it",
     w:"The body of a pull request on Favio’s own repository spoke about him in the third person and listed internal merge rules. Noticed by Favio.",
     c:"The body was rewritten before he merged it.",
     r:"Public text is written in Favio’s own voice and states facts, not the crew’s process. Before anything is posted, a search for process words.", l:["the practices"]}
  ].map((x, i) => ({a:"e2", id:`scar-e2-${i + 7}`, d:"16 Oct", t:x.t, w:esc(x.w), c:esc(x.c), r:esc(x.r), l:x.l, go:"#ledger", more:"Context"}));
  S.unshift(...NEW16, ...LEDGER.map((r, i) => ({a:"e2", id:`scar-e2-${i + 1}`, d:r.d, t:r.m, w:`${esc(r.w)} Noticed by ${esc(r.who)}.`, c:esc(r.c), r:esc(r.b), l:r.l, go:"#ledger"})));
  const wall = $("#scars"), filt = $("#scarFilt");
  const name = Object.fromEntries(AREAS);
  wall.innerHTML = S.map(s => `<article class="scar${s.id ? " e2" : ""}" data-a="${s.a}"${s.id ? ` id="${s.id}"` : ""}><div class="hd"><span>${esc(s.d)}</span><span class="ar">${esc(name[s.a])}</span></div><h3>${esc(s.t)}</h3>
    <dl><div><dt>What happened</dt><dd>${links(s.w)}</dd></div><div class="cost"><dt>What it cost</dt><dd>${s.c}</dd></div></dl>
    <div class="rule"><div class="k">The rule now</div><p>${links(s.r)}</p></div>
    <div class="lives"><span class="k">Lives in</span>${s.l.map(x => `<span class="chip">${esc(x)}</span>`).join("")}<a href="${s.go}">${s.more || (s.id ? "Its practice" : "Context")}</a></div></article>`).join("");
  $("#scarN").innerHTML = `${S.length}`;
  filt.innerHTML = AREAS.map(([k, l], i) => `<button type="button" data-a="${k}" aria-pressed="${i === 0}">${esc(l)}<small>${k === "all" ? S.length : S.filter(s => s.a === k).length}</small></button>`).join("");
  const pickArea = b => { filt.querySelectorAll("button").forEach(x => x.setAttribute("aria-pressed", x === b ? "true" : "false"));
    wall.querySelectorAll(".scar").forEach(c => { c.hidden = !(b.dataset.a === "all" || c.dataset.a === b.dataset.a); }); };
  filt.addEventListener("click", e => { const b = e.target.closest("button"); if (b) pickArea(b); });
  /* a ledger card's link opens its filter */
  document.addEventListener("click", e => { const a = e.target.closest('a[href^="#scar-e2-"]'); if (a) pickArea(filt.querySelector('[data-a="e2"]')); });
  const W = [
    ["Critic on the storyboard","Blockers caught before any scene was built."],
    ["Independent reviewers on every number","A fresh review session found a fairer clock in a film’s data."],
    ["Claims ledgers","Every sentence sourced, with a “will not claim” list."],
    ["One Devin machine for many turns","13 jobs on one machine on 9 Oct."],
    ["Cutting footage from a transcript","With a speaker check before each cut."],
    ["Mac review against main","Caught the 11–21 ms macOS audio offset."],
    ["Blind votes over AI judges","The judge preferred 0.2.0, and Favio’s blind vote went to lean 0.3.0."],
    ["Writing state to files","STATE.md, OVERNIGHT.md, PLAN.md: compactions and restarts lose nothing."],
    ["A shared memory repo","Read by every session and by Devin."],
    ["Green before release","0.4.2 waited a day for every check on all four systems."]
  ];
  $("#worked").innerHTML = W.map(w => `<div><b>${esc(w[0])}</b><span>${esc(w[1])}</span></div>`).join("");
})();


})();

(() => {
  document.querySelectorAll("#starter .kit-copy").forEach(btn => {
    btn.addEventListener("click", () => {
      const code = btn.closest(".kit-card").querySelector("pre code");
      const done = ok => { btn.textContent = ok ? "Copied" : "Selected"; setTimeout(() => { btn.textContent = "Copy"; }, 1600); };
      const select = () => { const r = document.createRange(); r.selectNodeContents(code); const s = getSelection(); s.removeAllRanges(); s.addRange(r); done(false); };
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(code.textContent).then(() => done(true), select);
      else select();
    });
  });
  const rm = window.matchMedia("(prefers-reduced-motion: reduce)");
  const loops = [...document.querySelectorAll("#drawn video")];
  const play = v => { const p = v.play(); if (p && p.catch) p.catch(() => {}); };
  /* Every loop can be stopped (WCAG 2.2.2): a Pause/Play button on each loop, or a click on the loop, toggles it, and a
     loop the reader paused stays paused when it scrolls back into view. Reduced motion: native controls, no autoplay. */
  const held = new WeakSet(), btns = new Map();
  const label = v => { const b = btns.get(v); if (!b) return; const word = v.paused ? "Play" : "Pause";
    b.textContent = word; b.setAttribute("aria-label", word + ": " + v.getAttribute("aria-label")); };
  const toggle = v => { if (v.paused) { held.delete(v); play(v); } else { held.add(v); v.pause(); } };
  const native = () => loops.forEach(v => { v.pause(); v.controls = true; const b = btns.get(v); if (b) b.hidden = true; });
  loops.forEach(v => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "loop-btn";
    b.addEventListener("click", () => toggle(v));
    v.addEventListener("click", () => { if (!v.controls) toggle(v); });
    v.addEventListener("play", () => label(v)); v.addEventListener("pause", () => label(v));
    const cap = v.parentElement.querySelector("figcaption");   /* in the caption, so it never covers the drawing */
    if (cap) cap.prepend(b); else v.after(b);
    btns.set(v, b); label(v);
  });
  if (rm.matches || !("IntersectionObserver" in window)) native();
  else {
    const io = new IntersectionObserver(es => es.forEach(e => {
      const v = e.target;
      if (rm.matches) return;
      if (e.isIntersecting) { if (!held.has(v)) play(v); } else v.pause();
    }), {rootMargin: "120px 0px"});
    loops.forEach(v => io.observe(v));
  }
  rm.addEventListener("change", () => { if (rm.matches) native(); });
})();
