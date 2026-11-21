/* Progress page of concept-mining. Reads data/site.json, written by tools/site/build_site.py. */
"use strict";
const GH = "https://github.com/hora-algebra/concept-mining/blob/main/";
const fmt = d3.format(",");
const short = v => v >= 1e6 ? (v / 1e6).toFixed(2) + " M" : v >= 1e4 ? (v / 1e3).toFixed(1) + " k" : fmt(v);
const pct = v => v >= 0.1 ? Math.round(v * 100) + "%" : v >= 0.001 ? (v * 100).toFixed(1) + "%" : (v * 100).toFixed(2) + "%";
const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const isOther = p => /other parts\)$/.test(p);
const showPart = p => isOther(p) ? p.slice(1, -1) : p === "(top)" ? "top level" : p;
const showFolder = f => f.replace("(top)", " (top level)");
const norm = t => { let p = t.trim().replace(/^\/+|\/+$/g, "").replace(/\//g, ".").replace(/\.lean$/, "").split(".").filter(Boolean); if (p[0] === "CFSG") p = p.slice(1); return p; };
const inside = (t, outer) => { const a = norm(t), b = norm(outer); return b.every((x, i) => a[i] === x); };
const store = { get(k, d) { try { return localStorage.getItem(k) || d; } catch (e) { return d; } }, set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} } };

let D, SNAP, folders, TOT;
const state = { area: store.get("cm-area", "lines"), color: store.get("cm-color", "progress"), scope: "all", t: 0 };

fetch("data/site.json").then(r => r.json()).then(init).catch(e => {
  document.getElementById("map").outerHTML = `<p class="empty">Could not load the data (${esc(e.message)}). If you opened the file directly, serve the folder over HTTP instead, for example <code>python3 -m http.server -d docs/site</code>.</p>`;
});

function init(data) {
  D = data;
  document.getElementById("example").hidden = !D.example;
  folders = D.map.folders;
  TOT = { lines: d3.sum(folders, f => d3.sum(f.parts, p => p.lines)), used: d3.sum(folders, f => d3.sum(f.parts, p => p.used)) };
  SNAP = [{ date: null, removed: {}, concepts: [] }].concat(D.snapshots);
  state.t = SNAP.length - 1;
  document.querySelectorAll("[data-gh]").forEach(a => a.href = GH + a.dataset.gh);
  header(); timeControl(); mapControls(); layout(); table(); timeline(); ranking(); work(); candidates(); footer();
  let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { layout(); timeline(); }, 120); });
}

/* ---------- header ---------- */
function header() {
  const c = D.ledger.concepts;
  const saved = d3.sum(c, x => x.lines_saved);
  const names = new Set(c.map(x => x.concept));
  const active = D.work.filter(w => w.status === "in-progress" || w.status === "claimed");
  document.getElementById("lead-lines").textContent = Math.round(D.summary.lines_in_declarations / 1e6) + " million";
  const k = [
    [short(D.summary.lines_in_declarations), `lines in ${fmt(D.summary.declarations)} definitions and theorems, before any refactoring`],
    [saved ? fmt(saved) : "0", saved ? "lines removed so far, as recorded in the ledger" : "lines removed so far: the first trial is under way"],
    [String(names.size), names.size === 1 ? "concept found" : "concepts found"],
    [String(active.length), active.length === 1 ? "part being refactored now" : "parts being refactored now"]
  ];
  document.getElementById("kpis").innerHTML = k.map(([v, l]) => `<div class="kpi"><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div></div>`).join("");
  const label = { done: "Done", active: "Now", next: "Next" };
  document.getElementById("stages").innerHTML = D.stages.map(s =>
    `<li class="${esc(s.status)}"><span class="st">${label[s.status] || ""}</span><b>${esc(s.stage)}. ${esc(s.title)}</b><p>${esc(s.summary)}</p></li>`).join("");
}

/* ---------- status of a part ---------- */
function workFor(f, p) {
  return D.work.filter(w => w.folder === f && (w.part == null || w.part === p));
}
function statusOf(f, p, t) {
  const key = f + "/" + p;
  if ((SNAP[t].removed[key] || 0) > 0) return "done";
  if (t !== SNAP.length - 1) return "idle";
  const w = workFor(f, p).map(x => x.status);
  if (w.includes("done")) return "done";
  if (w.includes("in-progress") || w.includes("claimed")) return "doing";
  if (w.includes("open")) return "open";
  return "idle";
}
const STATUS = [
  { k: "done", name: "Lines removed" }, { k: "doing", name: "Being refactored" },
  { k: "open", name: "Open for a volunteer" }, { k: "idle", name: "Not started" }
];
function touched() {
  const s = new Set(D.work.map(w => w.folder));
  SNAP.forEach(x => Object.keys(x.removed).forEach(k => s.add(k.split("/")[0])));
  return s;
}

/* ---------- controls ---------- */
function timeControl() {
  const slider = document.getElementById("slider"), play = document.getElementById("play");
  slider.max = SNAP.length - 1; slider.value = state.t;
  const single = SNAP.length < 2;
  slider.disabled = single; play.disabled = single;
  slider.addEventListener("input", () => { stop(); state.t = +slider.value; layout(); });
  let timer = null;
  function stop() { if (timer) { clearInterval(timer); timer = null; play.textContent = "▶"; play.setAttribute("aria-label", "Play through time"); } }
  play.addEventListener("click", () => {
    if (timer) return stop();
    if (state.t >= SNAP.length - 1) { state.t = 0; slider.value = 0; layout(); }
    play.textContent = "❚❚"; play.setAttribute("aria-label", "Pause");
    timer = setInterval(() => {
      if (state.t >= SNAP.length - 1) return stop();
      state.t++; slider.value = state.t; layout();
    }, 1500);
  });
}
function whenText() {
  const s = SNAP[state.t];
  const el = document.getElementById("when");
  if (SNAP.length < 2) {
    el.innerHTML = `<b>Start: the stage 1 map.</b> <span>No refactoring has been recorded yet. Once the ledger has entries, slide or press play to watch the map change.</span>`;
    return;
  }
  const removed = d3.sum(Object.values(s.removed));
  el.innerHTML = s.date == null
    ? `<b>Start</b> <span>the stage 1 map, before any refactoring</span>`
    : `<b>${esc(s.date)}</b> <span>${s.concepts.length ? "new: " + s.concepts.map(esc).join(", ") + ". " : ""}${fmt(removed)} lines removed on the map so far.</span>`;
}
function mapControls() {
  const work = touched();
  document.querySelectorAll("[data-area]").forEach(b => b.addEventListener("click", () => { state.area = b.dataset.area; store.set("cm-area", state.area); layout(); }));
  document.querySelectorAll("[data-color]").forEach(b => b.addEventListener("click", () => { state.color = b.dataset.color; store.set("cm-color", state.color); layout(); }));
  document.querySelectorAll("[data-scope]").forEach(b => {
    if (b.dataset.scope === "work" && !work.size) b.disabled = true;
    b.addEventListener("click", () => { state.scope = b.dataset.scope; layout(); });
  });
  document.addEventListener("pointerdown", e => { if (!e.target.closest(".leaf")) tipHide(); });
}
function pressed() {
  document.querySelectorAll("[data-area]").forEach(b => b.setAttribute("aria-pressed", b.dataset.area === state.area));
  document.querySelectorAll("[data-color]").forEach(b => b.setAttribute("aria-pressed", b.dataset.color === state.color));
  document.querySelectorAll("[data-scope]").forEach(b => b.setAttribute("aria-pressed", b.dataset.scope === state.scope));
}

/* ---------- map ---------- */
const mapEl = document.getElementById("map"), tip = document.getElementById("tip");
const leafEl = new Map(), foldEl = new Map();
function layout() {
  pressed(); whenText();
  const snap = SNAP[state.t], work = touched();
  const shown = folders.filter(f => state.scope === "all" || work.has(f.folder));
  const tree = { name: "CFSG", children: D.map.fields.map(fl => ({ name: fl.name, children: shown.filter(f => f.field === fl.key).map(f => ({
    name: f.folder, folder: f, children: f.parts.map(p => {
      const rem = state.area === "lines" ? Math.min(snap.removed[f.folder + "/" + p.part] || 0, p.lines) : 0;
      const kept = { name: p.part, part: p, kind: "kept", v: state.area === "lines" ? p.lines - rem : p.used, rem };
      return { name: p.part, part: p, children: rem > 0 ? [kept, { name: p.part, part: p, kind: "gone", v: rem, rem }] : [kept] };
    }) })) })).filter(x => x.children.length) };
  const W = mapEl.clientWidth, narrow = W < 560;
  const H = Math.round(narrow ? W * 1.45 : Math.max(420, Math.min(W * 0.6, 700)));
  mapEl.style.height = H + "px";
  const root = d3.hierarchy(tree).sum(d => d.children ? 0 : Math.max(d.v, 0)).sort((a, b) => b.value - a.value);
  const head = n => n.depth === 2 && n.value / root.value > (narrow ? 0.03 : 0.011);
  d3.treemap().size([W, H]).round(true).tile(d3.treemapSquarify.ratio(1.2))
    .paddingOuter(n => n.depth === 0 ? 4 : n.depth === 1 ? 3 : 0)
    .paddingTop(n => head(n) ? 19 : n.depth === 0 ? 4 : n.depth === 1 ? 3 : 0)
    .paddingInner(n => n.depth === 3 ? 0 : 2)(root);
  const seenF = new Set(), seenL = new Set();
  root.each(n => {
    if (n.depth === 2) {
      const key = n.data.name; seenF.add(key);
      let el = foldEl.get(key);
      if (!el) { el = document.createElement("div"); el.className = "fold"; mapEl.appendChild(el); foldEl.set(key, el); }
      const on = head(n) && n.x1 - n.x0 > 44;
      Object.assign(el.style, { left: n.x0 + "px", top: n.y0 + "px", width: (n.x1 - n.x0) + "px", height: "19px", opacity: on ? 1 : 0, display: "" });
      const g = n.data.folder.gloss; el.textContent = showFolder(key);
      if (g && n.x1 - n.x0 > 210) { const s = document.createElement("small"); s.textContent = g; el.append(s); }
    }
    if (n.depth === 4) {
      const fNode = n.parent.parent, f = fNode.data.folder, p = n.data.part, key = f.folder + "/" + p.part + "#" + n.data.kind;
      seenL.add(key);
      let el = leafEl.get(key);
      if (!el) {
        el = document.createElement("div"); el.appendChild(document.createElement("span")); mapEl.appendChild(el); leafEl.set(key, el);
        el.addEventListener("pointermove", e => tipShow(e, el));
        el.addEventListener("pointerdown", e => tipShow(e, el));
        el.addEventListener("pointerleave", tipHide);
        if (n.data.kind === "gone") Object.assign(el.style, { left: (n.x1) + "px", top: n.y0 + "px", width: "0px", height: (n.y1 - n.y0) + "px" });
      }
      el._d = { f, p, kind: n.data.kind, rem: n.data.rem };
      const st = statusOf(f.folder, p.part, state.t);
      el.className = "leaf " + (n.data.kind === "gone" ? "gone" : state.color === "field" ? "k-" + f.field : "s-" + st);
      const w = n.x1 - n.x0, h = n.y1 - n.y0;
      // let the browser register the starting box of a new element before moving it
      requestAnimationFrame(() => Object.assign(el.style, { left: n.x0 + "px", top: n.y0 + "px", width: w + "px", height: h + "px", display: "" }));
      el.style.padding = (w < 14 || h < 14) ? "0" : "";
      let t = "";
      if (n.data.kind === "gone") t = w > 60 && h > 17 ? "removed" : "";
      else {
        const biggest = fNode.children[0] === n.parent;
        t = head(fNode) ? (p.part.startsWith("(") && !isOther(p.part) ? "" : showPart(p.part)) : (biggest ? showFolder(f.folder) : "");
      }
      el.firstChild.textContent = (w > 30 && h > 17 && t.length * 6.4 + 8 < w * 1.6) ? t : "";
      let b = el.querySelector(".badge");
      const share = n.data.rem / p.lines;
      if (n.data.kind === "kept" && n.data.rem > 0 && w > 44 && h > 30) {
        if (!b) { b = document.createElement("span"); b.className = "badge"; el.appendChild(b); }
        b.textContent = "−" + pct(share);
      } else if (b) b.remove();
    }
  });
  foldEl.forEach((el, k) => { if (!seenF.has(k)) el.style.display = "none"; });
  leafEl.forEach((el, k) => { if (!seenL.has(k)) { if (k.endsWith("#gone")) { el.remove(); leafEl.delete(k); } else el.style.display = "none"; } });
  legend(shown);
}
function legend(shown) {
  const el = document.getElementById("legend");
  const hasGone = state.area === "lines" && Object.keys(SNAP[state.t].removed).length > 0;
  if (state.color === "field") {
    const tot = d3.sum(shown, f => d3.sum(f.parts, p => p[state.area]));
    el.innerHTML = D.map.fields.map(fl => {
      const v = d3.sum(shown.filter(f => f.field === fl.key), f => d3.sum(f.parts, p => p[state.area]));
      return v ? `<li><i class="k-${fl.key}"></i>${esc(fl.name)}<span class="v">${pct(v / tot)}</span></li>` : "";
    }).join("") + (hasGone ? `<li><i class="gone"></i>Removed lines</li>` : "");
  } else {
    el.innerHTML = STATUS.map(s => `<li><i class="s-${s.k}"></i>${s.name}</li>`).join("") + (hasGone ? `<li><i class="gone"></i>Removed lines</li>` : "");
  }
}
function tipShow(e, el) {
  const { f, p, kind, rem } = el._d;
  document.querySelectorAll(".leaf.hot").forEach(x => x.classList.remove("hot")); el.classList.add("hot");
  const st = STATUS.find(s => s.k === statusOf(f.folder, p.part, state.t)).name;
  const w = workFor(f.folder, p.part)[0];
  tip.innerHTML = `<b>${esc(showFolder(f.folder))} ▸ ${esc(showPart(p.part))}</b>${f.gloss ? esc(f.gloss) + "<br>" : ""}<span class="n">` +
    `${fmt(p.lines)} lines (${pct(p.lines / TOT.lines)} of all)<br>used ${fmt(p.used)} times by other parts<br>` +
    (rem > 0 ? `${fmt(rem)} lines removed (${pct(rem / p.lines)} of this part)<br>` : "") +
    `</span>Status: ${esc(st)}${w && state.t === SNAP.length - 1 ? " (" + esc(w.who) + ")" : ""}` + (kind === "gone" ? "<br><i>Hatched: lines already removed.</i>" : "");
  tip.hidden = false;
  const r = tip.getBoundingClientRect();
  let x = e.clientX + 14, y = e.clientY + 14;
  if (x + r.width > innerWidth - 8) x = Math.max(8, e.clientX - r.width - 14);
  if (y + r.height > innerHeight - 8) y = Math.max(8, e.clientY - r.height - 14);
  tip.style.left = x + "px"; tip.style.top = y + "px";
}
function tipHide() { tip.hidden = true; document.querySelectorAll(".leaf.hot").forEach(x => x.classList.remove("hot")); }
function table() {
  const fname = Object.fromEntries(D.map.fields.map(f => [f.key, f.name]));
  document.getElementById("tbl").innerHTML = "<tr><th>Folder</th><th>Content</th><th>Field</th><th class='r'>Lines</th><th class='r'>Times used</th></tr>" +
    folders.map(f => `<tr><td>${esc(showFolder(f.folder))}</td><td>${esc(f.gloss)}</td><td>${esc(fname[f.field])}</td><td class="r">${fmt(d3.sum(f.parts, p => p.lines))}</td><td class="r">${fmt(d3.sum(f.parts, p => p.used))}</td></tr>`).join("");
}

/* ---------- timeline ---------- */
function series() {
  const h = D.ledger.history, c = D.ledger.concepts;
  const out = [];
  d3.groups(h, x => x.target).forEach(([t, rows]) => out.push({ target: t, pts: rows.map(r => ({ date: r.date, v: r.lines_total })).sort((a, b) => a.date < b.date ? -1 : 1) }));
  // targets with concepts but no history: rebuild from before/after
  d3.groups(c, x => x.target).forEach(([t, rows]) => {
    if (out.some(s => inside(t, s.target))) return;
    rows = rows.slice().sort((a, b) => a.date < b.date ? -1 : 1);
    out.push({ target: t, pts: [{ date: rows[0].date, v: rows[0].lines_before, start: true }].concat(rows.map(r => ({ date: r.date, v: r.lines_after }))) });
  });
  out.forEach(s => { s.steps = c.filter(x => inside(x.target, s.target)).sort((a, b) => a.date < b.date ? -1 : 1); });
  return out;
}
let curSeries = 0;
function timeline() {
  const box = document.getElementById("timeline");
  const S = series();
  if (!S.length) {
    const w = D.work.filter(x => x.status === "in-progress")[0];
    box.innerHTML = `<div class="empty"><b>No refactoring recorded yet.</b>${w ? `The first trial is under way in <code>${esc(w.target)}</code>. ` : ""}When the first results land in the ledger, this chart shows the line count of each part going down, with the name of the concept at every step.</div>`;
    return;
  }
  curSeries = Math.min(curSeries, S.length - 1);
  const s = S[curSeries];
  const pick = S.length > 1 ? `<label class="small">Part <select id="pick">${S.map((x, i) => `<option value="${i}"${i === curSeries ? " selected" : ""}>${esc(x.target)}</option>`).join("")}</select></label>` : `<div class="small">${esc(s.target)}</div>`;
  box.innerHTML = `<div class="panel">${pick}<div id="chart"></div><ol class="steps" id="steps"></ol></div>`;
  if (S.length > 1) document.getElementById("pick").addEventListener("change", e => { curSeries = +e.target.value; timeline(); });
  const parse = d3.utcParse("%Y-%m-%d");
  const pts = s.pts.map(p => ({ ...p, d: parse(p.date) }));
  const W = Math.max(280, document.getElementById("chart").clientWidth), narrow = W < 560;
  const H = narrow ? 240 : 300, m = { t: 18, r: narrow ? 14 : 30, b: 30, l: narrow ? 52 : 64 };
  const svg = d3.select("#chart").append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img")
    .attr("aria-label", `Line count of ${s.target} over time`);
  let [x0, x1] = d3.extent(pts, p => p.d);
  if (+x0 === +x1) { x0 = d3.utcDay.offset(x0, -3); x1 = d3.utcDay.offset(x1, 3); }
  const x = d3.scaleUtc().domain([x0, x1]).range([m.l, W - m.r]);
  const [lo, hi] = d3.extent(pts, p => p.v), pad = (hi - lo) * 0.15 || hi * 0.03;
  const y = d3.scaleLinear().domain([lo - pad, hi + pad]).nice().range([H - m.b, m.t]);
  svg.append("g").attr("class", "grid").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(5).tickSize(-(W - m.l - m.r)).tickFormat("")).call(g => g.select(".domain").remove());
  svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - m.b})`).call(d3.axisBottom(x).ticks(narrow ? 3 : 6).tickFormat(d3.utcFormat("%b %d")));
  svg.append("g").attr("class", "axis").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(5).tickFormat(v => short(v))).call(g => g.select(".domain").remove());
  svg.append("path").datum(pts).attr("class", "series").attr("d", d3.line().curve(d3.curveStepAfter).x(p => x(p.d)).y(p => y(p.v)));
  svg.selectAll(".dot").data(pts).join("circle").attr("class", "dot").attr("r", 4).attr("cx", p => x(p.d)).attr("cy", p => y(p.v));
  // number each concept at the point where its step lands
  const valueAt = d => { let v = pts[0].v; pts.forEach(p => { if (p.d <= d) v = p.v; }); return v; };
  const ann = svg.append("g").attr("class", "ann");
  s.steps.forEach((c, i) => {
    const d = parse(c.date), cx = x(d), cy = y(valueAt(d));
    const g = ann.append("g").attr("transform", `translate(${cx},${cy})`);
    g.append("circle").attr("r", 9).attr("cy", -16).attr("fill", "var(--fg)");
    g.append("text").attr("class", "num").attr("y", -12).attr("text-anchor", "middle").text(i + 1);
    if (!narrow && s.steps.length <= 6) {
      const left = cx > W - 200;
      g.append("text").attr("x", left ? -14 : 12).attr("y", -12).attr("text-anchor", left ? "end" : "start")
        .text(c.concept.length > 28 ? c.concept.slice(0, 27) + "…" : c.concept);
    }
  });
  if (pts.length === 1) svg.append("text").attr("x", W / 2).attr("y", m.t + 14).attr("text-anchor", "middle").attr("fill", "var(--muted)").attr("font-size", 13).text("One measurement so far");
  document.getElementById("steps").innerHTML = s.steps.map((c, i) =>
    `<li><span class="k">${i + 1}</span><span class="d">${esc(c.date)}</span><span><b>${esc(c.concept)}</b> −${fmt(c.lines_saved)} lines</span></li>`).join("") +
    `<li class="small" style="border-top:0">Line counts are as recorded in the ledger for this part, which may count lines differently from the map.</li>`;
}

/* ---------- ranking ---------- */
function ranking() {
  const box = document.getElementById("rank");
  const g = d3.groups(D.ledger.concepts, c => c.concept).map(([name, rows]) => ({
    name, saved: d3.sum(rows, r => r.lines_saved), uses: d3.sum(rows, r => r.uses),
    meaning: (rows.find(r => r.meaning) || {}).meaning || "", targets: [...new Set(rows.map(r => r.target))], date: d3.min(rows, r => r.date)
  })).sort((a, b) => b.saved - a.saved);
  if (!g.length) {
    box.innerHTML = `<div class="empty"><b>No concepts yet.</b>The first concepts will come from the trial refactoring now under way. Each will be listed here with the lines it saved and a sentence on what it means mathematically.</div>`;
    return;
  }
  const max = g[0].saved || 1;
  box.innerHTML = `<div class="panel"><ol class="rank">${g.map((c, i) => `<li><span class="no">${i + 1}</span><span class="nm">${esc(c.name)}</span>
    <div class="track"><div class="fill" style="width:${Math.max(0.5, 78 * c.saved / max)}%"></div><span class="val">−${fmt(c.saved)} lines</span></div>
    ${c.meaning ? `<div class="mean">${esc(c.meaning)}</div>` : ""}
    <div class="meta">${c.targets.map(esc).join(", ")} · used ${fmt(c.uses)} times · first recorded ${esc(c.date)}</div></li>`).join("")}</ol></div>`;
}

/* ---------- work board ---------- */
function work() {
  const box = document.getElementById("work");
  if (!D.work.length) { box.innerHTML = `<p class="small">Nobody has claimed a part yet.</p>`; return; }
  box.innerHTML = `<table><tr><th>Part</th><th>Status</th><th>Who</th><th>What</th></tr>${D.work.map(w =>
    `<tr><td><code>${esc(w.target)}</code></td><td><span class="pill p-${esc(w.status)}">${esc(w.status.replace("-", " "))}</span></td><td>${esc(w.who)}</td><td>${esc(w.note)}${w.link ? ` <a href="${esc(w.link)}">details</a>` : ""}</td></tr>`).join("")}</table>`;
}
function slug(s) { return s.toLowerCase().replace(/[^\p{L}\p{N}\s_-]/gu, "").trim().replace(/\s/g, "-"); }
function candidates() {
  const kind = { name: ["No Lean needed"], refactor: ["Lean"], both: ["No Lean needed", "Lean"] };
  document.getElementById("cands").innerHTML = D.candidates.map(c => {
    const href = c.issue ? `https://github.com/hora-algebra/concept-mining/issues/${encodeURIComponent(c.issue)}` : GH + "docs/first-issues.md#" + slug(`${c.id}. ${c.title}`);
    const st = c.issue ? (c.status === "draft" ? "open" : c.status) : "draft";
    return `<div class="card"><div class="top"><span class="id">${esc(c.id)}</span><span class="pill p-${esc(st)}">${st === "draft" ? "not yet an issue" : esc(st)}</span>${kind[c.kind].map(k => `<span class="tag">${k}</span>`).join("")}</div>
      <h3>${esc(c.title)}</h3><div class="sz">${esc(c.size)} · ${esc(c.area)}</div><a class="go" href="${href}">Read the task →</a></div>`;
  }).join("");
}

/* ---------- footer ---------- */
function footer() {
  const errs = D.checks.errors;
  document.getElementById("foot").innerHTML = `
    <p>Data: the declaration graph of <a href="https://github.com/AxiomMath/CFSG">AxiomMath/CFSG</a> (proof-map build of commit <code>${esc(D.map.commit.slice(0, 7))}</code>), aggregated by <a href="https://github.com/hora-algebra/concept-mining">concept-mining</a>. Map sizes are ${esc(D.map.measure)}; "times used" counts direct references from declarations in other parts. References into Mathlib are not counted.</p>
    <p>Fields and folder descriptions were assigned from folder names and have not been reviewed by experts.</p>
    <p>The ledger is checked automatically on every pull request (consistent arithmetic, known parts, valid dates and commits) without building Lean; ${errs ? errs + " errors" : "no errors"} at the last build. Removed lines on the map are converted from the ledger's own line counts, part by part, so they are approximate.</p>
    <p><a href="${GH}README.md">About the project</a> · <a href="${GH}CONTRIBUTING.md">Contribute</a> · <a href="${GH}data/ledger">Ledger</a></p>`;
}
