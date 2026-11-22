// MILES x Rescue landing page / deck. No framework, no tracking. The only API is same-origin /ops/api/*.
'use strict';

// Where the QR code and "Try the concept" link point. Swap here only.
const APP_INSTALL_URL = 'https://miles.bolls.dev/app/';

const API = '/ops/api';
const HEALTH_MS = 15000;
const STATE_MS = 30000;
const C = { pfn: '#0ECAA0', ink: '#1A1A1A', bg: '#FDFDFC', wash: '#F1F1EF' };
const SVGNS = 'http://www.w3.org/2000/svg';
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)');
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const fmtInt = n => Math.round(n).toLocaleString('en-US');

function svg(tag, attrs = {}, text) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  if (text != null) el.textContent = text;
  return el;
}
function h(tag, cls, html) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (html != null) el.innerHTML = html;
  return el;
}

/* ---------------- scroll-linked rise + fade ----------------
   CSS scroll-driven animations do the work where supported (see home.css). Otherwise this one
   rAF-throttled scroll handler sets --p (0..1) per element from its position: the same mapping as the CSS
   range (starts when the element's top reaches the viewport bottom, done RISE px later, staggered by --i). */
const SCROLL_DRIVEN = typeof CSS !== 'undefined' && CSS.supports && CSS.supports('animation-timeline: view()');
function initReveal() {
  for (const s of $$('.slide')) $$('.r', s).forEach((el, i) => el.style.setProperty('--i', Math.min(i, 6)));
  if (SCROLL_DRIVEN || reduceMotion.matches) return;
  const els = $$('.slide:not(.hero) .r');
  let queued = false;
  const update = () => {
    queued = false;
    if (isDeck()) return;
    const vh = innerHeight, len = matchMedia('(max-width: 820px)').matches ? 150 : 220;
    const tops = els.map(el => el.getBoundingClientRect().top);          // read all, then write all
    els.forEach((el, k) => {
      const i = Math.min(+el.style.getPropertyValue('--i') || 0, 6);
      const p = Math.max(0, Math.min(1, (vh - tops[k] - i * 14) / len));
      el.style.setProperty('--p', p === 1 ? '1' : p.toFixed(3));
    });
  };
  const onScroll = () => { if (!queued) { queued = true; requestAnimationFrame(update); } };
  update();
  document.documentElement.classList.add('sl');
  addEventListener('scroll', onScroll, { passive: true });
  addEventListener('resize', onScroll);
}

/* ---------------- charts ---------------- */
function timeline() {
  const el = $('#timeline'); if (!el) return;
  const x = hrs => 40 + hrs * (920 / 30), Y = 98;
  el.append(svg('rect', { x: x(12), y: Y - 22, width: x(30) - x(12), height: 22, fill: C.wash }));
  el.append(svg('text', { x: x(12) + 8, y: Y - 7, class: 'muted' }, 'stranded (12 h+)'));
  el.append(svg('line', { x1: x(0), x2: x(30), y1: Y, y2: Y, class: 'ax' }));
  for (let t = 0; t <= 30; t += 6) {
    el.append(svg('line', { x1: x(t), x2: x(t), y1: Y, y2: Y + 6, class: 'ax' }));
    el.append(svg('text', { x: x(t), y: Y + 24, 'text-anchor': 'middle', class: 'muted' }, t + ' h'));
  }
  // the gap we close
  el.append(svg('path', { d: `M${x(0)} 34 V28 H${x(24.6)} V34`, fill: 'none', stroke: C.ink, 'stroke-width': 1 }));
  el.append(svg('text', { x: (x(0) + x(24.6)) / 2, y: 20, 'text-anchor': 'middle', class: 'lbl' }, 'about a day earlier'));
  const mark = (hrs, label, cls, anchor) => {
    el.append(svg('line', { x1: x(hrs), x2: x(hrs), y1: 44, y2: Y, stroke: cls === 'pfn' ? C.pfn : C.ink, 'stroke-width': 1.2, 'stroke-dasharray': cls === 'dash' ? '3 3' : '' }));
    el.append(svg('circle', { cx: x(hrs), cy: Y, r: 6, fill: cls === 'pfn' ? C.pfn : cls === 'dash' ? C.bg : C.ink, stroke: cls === 'dash' ? C.ink : 'none' }));
    el.append(svg('text', { x: x(hrs) + (anchor === 'start' ? 8 : -8), y: 56, 'text-anchor': anchor, class: cls === 'pfn' ? 'pfn lbl' : 'lbl' }, label));
  };
  mark(0, 'Ride ends: we score it here', 'pfn', 'start');
  mark(18, 'Median stranded wait, 18 h', 'dash', 'end');
  mark(24.6, 'MILES relocation starts, median 24.6 h', 'ink', 'start');
  el.setAttribute('viewBox', '0 0 1060 140');
}

function aucTable() {
  const el = $('#auc-table'); if (!el) return;
  const rows = [
    { m: 'TabPFN', sub: '10k-row context, no tuning', auc: 0.846, ece: '0.010', hit: '58%', cls: 'row-pfn' },
    { m: 'GBM', sub: 'same 10k rows', auc: 0.825, ece: '0.030', hit: '54%' },
    { m: 'GBM', sub: 'all 208k rows', auc: 0.858, ece: '0.008', hit: '61%' },
    { m: 'Logistic regression', sub: 'all 208k rows', auc: 0.806, ece: '–', hit: '–', cls: 'row-weak' },
  ];
  const lo = 0.79, hi = 0.87, pct = v => ((v - lo) / (hi - lo)) * 100;
  for (const [t, c] of [['Model', 'h m-cell'], ['AUC, test week', 'h h-auc'], ['ECE', 'h'], ['Top-10% hit', 'h']]) {
    const d = h('div', c, t); d.setAttribute('role', 'columnheader'); el.append(d);
  }
  for (const r of rows) {
    const cls = r.cls || '';
    el.append(h('div', cls + ' m-cell', `<span class="m">${r.m}</span><span class="sub">${r.sub}</span>`));
    el.append(h('div', `${cls} c-auc`, `<div class="track"><i style="left:${pct(r.auc)}%"></i><b style="left:${pct(r.auc)}%">${r.auc.toFixed(3)}</b></div>`));
    el.append(h('div', `${cls} num`, r.ece));
    el.append(h('div', `${cls} num`, r.hit));
  }
  el.append(h('div', 'axis-cell'));
  const ax = h('div', 'axis-cell c-auc'), axis = h('div', 'axis');
  for (const t of [0.80, 0.82, 0.84, 0.86]) { const sp = h('span', '', t.toFixed(2)); sp.style.left = pct(t) + '%'; axis.append(sp); }
  ax.append(axis); el.append(ax, h('div', 'axis-cell'), h('div', 'axis-cell'));
}

function coldChart() {
  const el = $('#cold'); if (!el) return;
  const L = 64, R = 590, T = 24, B = 340;
  const x = n => L + ((Math.log10(n) - Math.log10(40)) / (Math.log10(1300) - Math.log10(40))) * (R - L);
  const y = v => B - ((v - 0.58) / (0.74 - 0.58)) * (B - T);
  for (const t of [0.60, 0.64, 0.68, 0.72]) {
    el.append(svg('line', { x1: L, x2: R, y1: y(t), y2: y(t), class: 'grid' }));
    el.append(svg('text', { x: L - 12, y: y(t) + 4, 'text-anchor': 'end', class: 'muted' }, t.toFixed(2)));
  }
  el.append(svg('line', { x1: L, x2: R, y1: B, y2: B, class: 'ax' }));
  for (const n of [50, 200, 1000]) {
    el.append(svg('line', { x1: x(n), x2: x(n), y1: B, y2: B + 6, class: 'ax' }));
    el.append(svg('text', { x: x(n), y: B + 24, 'text-anchor': 'middle' }, fmtInt(n)));
  }
  el.append(svg('text', { x: (L + R) / 2, y: B + 50, 'text-anchor': 'middle', class: 'muted' }, 'Labelled rides from the new city (log scale)'));
  el.append(svg('text', { x: 14, y: T - 6, class: 'muted' }, 'AUC'));
  const pfn = [[50, 0.665], [200, 0.688], [1000, 0.710]];
  el.append(svg('polyline', { points: pfn.map(([n, v]) => `${x(n)},${y(v)}`).join(' '), fill: 'none', stroke: C.pfn, 'stroke-width': 2.5 }));
  for (const [n, v] of pfn) {
    el.append(svg('circle', { cx: x(n), cy: y(v), r: 6, fill: C.pfn }));
    el.append(svg('text', { x: x(n), y: y(v) - 14, 'text-anchor': 'middle', class: 'pfn lbl' }, v.toFixed(3)));
  }
  el.append(svg('text', { x: x(200), y: y(0.688) - 40, 'text-anchor': 'middle', class: 'pfn lbl' }, 'TabPFN, Berlin in context'));
}

function byHour() {
  const el = $('#byhour'); if (!el) return;
  const pts = [[10, 16, '08–12'], [14, 22], [16, 30], [18, 41], [20, 46], [22, 45], [24, 40], [28, 24]];
  const L = 40, R = 385, T = 18, B = 190;
  const x = t => L + ((t - 8) / (28 - 8)) * (R - L), y = v => B - (v / 50) * (B - T);
  for (const t of [0, 25, 50]) {
    el.append(svg('line', { x1: L, x2: R, y1: y(t), y2: y(t), class: 'grid' }));
    el.append(svg('text', { x: L - 8, y: y(t) + 4, 'text-anchor': 'end', class: 'muted' }, t + '%'));
  }
  el.append(svg('line', { x1: L, x2: R, y1: B, y2: B, class: 'ax' }));
  for (const [t, lab] of [[8, '08'], [12, '12'], [16, '16'], [20, '20'], [24, '00'], [28, '04']]) {
    el.append(svg('text', { x: x(t), y: B + 20, 'text-anchor': 'middle', class: 'muted' }, lab + ':00'));
  }
  el.append(svg('polyline', { points: pts.map(([t, v]) => `${x(t)},${y(v)}`).join(' '), fill: 'none', stroke: C.ink, 'stroke-width': 2 }));
  for (const [t, v] of pts) el.append(svg('circle', { cx: x(t), cy: y(v), r: 3.5, fill: C.ink }));
  el.append(svg('text', { x: x(10), y: y(16) - 10, 'text-anchor': 'middle', class: 'lbl' }, '16%'));
  el.append(svg('text', { x: x(20), y: y(46) - 10, 'text-anchor': 'middle', class: 'lbl' }, '46% at 20:00'));
}

function byDist() {
  const el = $('#bydist'); if (!el) return;
  for (const [lab, v] of [['< 3 km', 7], ['3–6 km', 19], ['6–10 km', 31], ['10–15 km', 40], ['> 15 km', 46]]) {
    el.append(h('div', 'row', `<span>${lab}</span><div class="hb"><i style="width:${(v / 50) * 82}%"></i><b style="left:${(v / 50) * 82}%">${v}%</b></div>`));
  }
}

function oddsChart() {
  const el = $('#odds'); if (!el) return;
  const rows = [['Van', 5.5], ['Ride ends 18:00–24:00', 3.5], ['Large car', 3.1], ['Premium', 2.5], ['Ride ends 00:00–06:00', 1.7],
    ['Fuel under 15%', 1.5], ['Each 5 km from centre', 1.3], ['Electric', 0.8], ['100 more departures nearby (24 h)', 0.48]];
  const L = 260, R = 610, T = 20, step = 44;
  const lx = v => L + ((Math.log(v) - Math.log(0.28)) / (Math.log(7) - Math.log(0.28))) * (R - L);
  const B = T + rows.length * step;
  for (const t of [0.5, 1, 2, 5]) {
    el.append(svg('line', { x1: lx(t), x2: lx(t), y1: T - 8, y2: B, class: t === 1 ? 'ax' : 'grid' }));
    el.append(svg('text', { x: lx(t), y: B + 22, 'text-anchor': 'middle', class: 'muted' }, t + '×'));
  }
  el.append(svg('text', { x: lx(1) - 8, y: B + 46, 'text-anchor': 'end', class: 'muted' }, 'less likely to strand'));
  el.append(svg('text', { x: lx(1) + 8, y: B + 46, class: 'muted' }, 'more likely to strand'));
  rows.forEach(([lab, v], i) => {
    const cy = T + i * step + step / 2;
    el.append(svg('text', { x: L - 18, y: cy + 5, 'text-anchor': 'end', class: 'lbl', 'font-size': 15 }, lab));
    el.append(svg('line', { x1: lx(1), x2: lx(v), y1: cy, y2: cy, stroke: C.ink, 'stroke-width': 2 }));
    el.append(svg('circle', { cx: lx(v), cy, r: 6.5, fill: C.ink }));
    el.append(svg('text', { x: lx(v) + (v >= 1 ? 13 : -13), y: cy + 5, 'text-anchor': v >= 1 ? 'start' : 'end', class: 'lbl', 'font-size': 15 }, (v < 1 ? v.toFixed(2) : v.toFixed(1)) + '×'));
  });
}

function ranges() {
  const el = $('#ranges'); if (!el) return;
  const max = 1.4, pct = v => (v / max) * 100;
  const rows = [
    ['5% accept', '', 0.13, 0.30, null, '€130k–300k'],
    ['10% accept', '', 0.26, 0.61, 0.42, '€260k–610k, mid €420k'],
    ['20% accept', '', 0.53, 1.2, null, '€530k–1.2M'],
  ];
  for (const [a, s, lo, hi, mid, lab] of rows) {
    const tr = `<i style="left:${pct(lo)}%;width:${pct(hi - lo)}%"></i>` + (mid ? `<i class="mid" style="left:${pct(mid)}%"></i>` : '') +
      (pct(hi) > 62 ? `<b class="flip" style="left:${pct(lo)}%">${lab}</b>` : `<b style="left:${pct(hi)}%">${lab}</b>`);
    el.append(h('div', 'row', `<span><b>${a}</b>${s}</span><div class="tr">${tr}</div>`));
  }
  el.append(h('div', 'row', `<span><b>Alternative view</b>not additive: up to ≈€1.3M</span><div class="tr"><i class="alt" style="left:0;width:${pct(1.3)}%"></i></div>`));
  const ax = h('div', 'axis');
  for (const [v, t] of [[0, '€0'], [0.5, '€0.5M'], [1, '€1M']]) { const sp = h('span', '', t); sp.style.left = pct(v) + '%'; ax.append(sp); }
  el.append(ax);
}

/* ---------------- live: TabPFN scorer status + embedded console ---------------- */
const live = { ok: null, fails: 0, health: null, counters: null, moves: null, fetchedAt: 0, snapshot: null, snapAt: null };

async function getJSON(path, ms = 8000) {
  const ctl = new AbortController(), t = setTimeout(() => ctl.abort(), ms);
  try {
    const r = await fetch(path, { cache: 'no-store', signal: ctl.signal });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return await r.json();
  } finally { clearTimeout(t); }
}

async function loadSnapshot() {
  if (live.snapshot) return live.snapshot;
  try { live.snapshot = await getJSON('/home/snapshot.json'); } catch { live.snapshot = null; }
  return live.snapshot;
}

function agoText(sec) {
  if (sec == null || !isFinite(sec)) return '–';
  sec = Math.max(0, sec);
  if (sec < 90) return `${Math.round(sec)} s ago`;
  if (sec < 5400) return `${Math.round(sec / 60)} min ago`;
  return `${(sec / 3600).toFixed(1)} h ago`;
}
function berlinTime(iso, withDate) {
  const o = { timeZone: 'Europe/Berlin', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' };
  if (withDate) Object.assign(o, { day: 'numeric', month: 'short', year: 'numeric' });
  return new Date(iso).toLocaleString('en-GB', o);
}

function rideEndAge() {
  const hl = live.health; if (!hl?.live?.ber_last_ride_end_at) return null;
  const base = (Date.parse(hl.now) - Date.parse(hl.live.ber_last_ride_end_at)) / 1000;
  return live.ok ? base + (Date.now() - live.fetchedAt) / 1000 : base;
}

function renderLive() {
  const hl = live.health, tp = hl?.tabpfn, set = (k, v, cls) => { const d = $(`[data-k="${k}"]`); if (d) { d.innerHTML = v; d.className = cls || ''; } };
  const age = rideEndAge();
  if (tp) {
    set('ago', live.ok ? agoText(age) : (age != null ? `${agoText(age).replace(' ago', '')} <small>before snapshot</small>` : '–'));
    set('rows', fmtInt(tp.rows_tabpfn), 'pfn');
    set('calls', `${fmtInt(tp.ok)} <small>of ${fmtInt(tp.calls)}</small>`);
    set('lat', tp.latency_p50_s != null ? `${tp.latency_p50_s.toFixed(2)} s` : '–');
    set('fb', tp.fallback_rate != null ? `${(tp.fallback_rate * 100).toFixed(1)}%` : '–');
  }
  if (live.counters && live.moves) set('flagged', `${fmtInt(live.counters.stranding_risk_now)} <small>→</small> ${fmtInt(live.moves.relocate)}`);
  else if (live.counters) set('flagged', `${fmtInt(live.counters.stranding_risk_now)} <small>→ –</small>`);
  liveCaption();

  const st = $('#live-status'), pulse = $('[data-live="hero"]'), badge = $('#embed-badge');
  const stale = live.ok && age != null && age > 1800;
  if (live.ok) {
    st.className = 'status r on';
    st.textContent = stale
      ? `Scorer is up, but no Berlin ride end for ${agoText(age).replace(' ago', '')}. Updated ${berlinTime(hl.now)}.`
      : `Updated ${berlinTime(new Date(live.fetchedAt).toISOString())} Berlin time, every ${HEALTH_MS / 1000} s. Counters since service start.`;
    pulse.className = 'pulse r on ok';
    pulse.querySelector('span').textContent = stale ? 'Live scorer is up. Berlin feed quiet right now.' : `Running now: latest Berlin ride end ${agoText(age)}, scored by TabPFN.`;
  } else if (live.ok === false) {
    st.className = 'status r on down';
    st.textContent = live.snapAt ? `Live feed unavailable. Showing the last snapshot, taken ${berlinTime(live.snapAt, true)} Berlin time.` : 'Live feed unavailable, and no snapshot could be loaded.';
    pulse.className = 'pulse r on down';
    pulse.querySelector('span').textContent = 'Live feed unavailable right now. See the last snapshot.';
  }
  if (badge && embed.mode === 'live') badge.className = 'live-badge ' + (live.ok === false ? 'down' : live.ok ? 'ok' : '');
}

async function pollHealth() {
  try {
    live.health = await getJSON(`${API}/health`);
    if (!live.health?.tabpfn) throw new Error('no tabpfn block');
    live.ok = true; live.fails = 0; live.fetchedAt = Date.now();
    if (embed.mode === 'rec' && !embed.user && !embed.failed) setEmbedMode('live', true);
  } catch {
    live.fails++;
    if (live.ok === null || live.fails >= 2) {
      const s = await loadSnapshot();
      live.ok = false;
      if (s) { live.health = s.health; live.counters = s.counters; live.moves = s.moves_summary || null; live.snapAt = s.captured_at; }
      if (isDeck()) setEmbedMode('rec', true);
    }
  }
  renderLive();
}
async function pollState() {
  if (live.ok === false) return;
  try {
    const [s, m] = await Promise.all([getJSON(`${API}/state?source=live&limit=0`), getJSON(`${API}/moves?source=live`)]);
    live.counters = s.counters; live.moves = m.summary; renderLive();
  } catch { /* health handles the down state */ }
}
// The caption under the console says exactly what is on screen: live, the recording, or the snapshot.
function liveCaption() {
  const el = $('#live-caption'); if (!el) return;
  if (live.ok === false) el.textContent = live.snapAt ? `Live feed unavailable. Console: recording, 22 Nov. Numbers on the right: snapshot, ${berlinTime(live.snapAt, true)} Berlin time, so they can differ from the recording.` : 'Live feed unavailable. Console: recording, 22 Nov.';
  else if (embed.mode === 'rec') el.textContent = 'Console: recording, 22 Nov. The numbers on the right are live, so they can differ from the recording (counters since service start).';
  else el.textContent = 'Live: 2026 Berlin ride ends from our scraper, scored by the TabPFN API with a June 2024 context. Counters since service start.';
}

/* embedded console: the real /ops page, rendered at 1440x900 and scaled into a 16:10 frame */
const embed = { mode: 'live', started: false, failed: false, user: false };

function fitEmbed() {
  const scr = $('#embed'), fr = $('#ops-frame'); if (!scr || !fr) return;
  fr.style.transform = `scale(${scr.clientWidth / 1440})`;
}
async function startEmbed() {
  if (embed.started) return; embed.started = true;
  const fr = $('#ops-frame');
  let ok = false;
  try { const r = await fetch('/ops/', { cache: 'no-store' }); ok = r.ok; } catch { ok = false; }
  if (!ok) return failEmbed();
  const timer = setTimeout(failEmbed, 20000);
  fr.addEventListener('load', () => {
    clearTimeout(timer);
    let good = false;
    try { good = !!fr.contentDocument?.querySelector('#app, #list, #map'); } catch { good = false; }
    if (!good) failEmbed();
  }, { once: true });
  fr.src = '/ops/';
}
function failEmbed() {
  embed.failed = true;
  if (!embed.user) setEmbedMode('rec', true);
}
function setEmbedMode(mode, auto) {
  if (!auto) embed.user = true;
  embed.mode = mode;
  const scr = $('#embed'); if (!scr) return;
  scr.dataset.mode = mode;
  $$('.toggle button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.mode === mode)));
  const badge = $('#embed-badge');
  liveCaption();
  if (mode === 'rec') {
    badge.className = 'live-badge rec'; badge.lastChild.textContent = embed.failed ? 'Recording, 22 Nov (live console unreachable)' : 'Recording of the live console, 22 Nov';
    const v = $('#ops-video');
    if (!v.src) { v.src = v.dataset.src; v.load(); }
    v.play?.().catch(() => {});
  } else {
    badge.lastChild.textContent = 'Live';
    if (!embed.started) startEmbed();
    renderLive();
  }
}
function initEmbed() {
  const scr = $('#embed'); if (!scr) return;
  scr.dataset.mode = 'live';
  const v = $('#ops-video');
  v.addEventListener('loadeddata', () => { scr.dataset.video = 'ok'; });
  v.addEventListener('error', () => { scr.dataset.video = 'missing'; });
  $$('.toggle button').forEach(b => b.addEventListener('click', () => setEmbedMode(b.dataset.mode)));
  if ('ResizeObserver' in window) new ResizeObserver(fitEmbed).observe(scr); else addEventListener('resize', fitEmbed);
  fitEmbed();
  const io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) { io.disconnect(); if (embed.mode === 'live') startEmbed(); } }, { rootMargin: '800px 0px' });
  io.observe(scr);
}

/* ---------------- interactive concept app inside the CSS iPhone ----------------
   One live iframe only: the phone on slide 1. The frame draws the status bar and home indicator;
   /app/?embed=1 keeps its own controls clear of them (54 px top, 34 px bottom). Slide 9 shows a still
   of the same app in the same frame, plus the phone recording once media/app.mp4 exists.
   Phones (scroll layout) get no nested phone: just an "Open the interactive demo" button. */
const APP_EMBED_URL = '/app/?embed=1';
const WIDE = matchMedia('(min-width: 821px)');
const device = { started: false, timer: null };

function fitDevice() {
  for (const wrap of $$('.device-wrap')) {
    const f = parseFloat(wrap.dataset.fit) || 0.72;
    const hero = wrap.classList.contains('hero-device');
    const pw = wrap.parentElement.getBoundingClientRect().width;
    const maxH = WIDE.matches ? Math.min(innerHeight * f, 920) : 700;
    const maxW = WIDE.matches ? pw * (hero ? 0.42 : 0.34) : Math.min(pw, 360);
    const s = Math.max(0.35, Math.min(maxH / 872, maxW / 418));
    wrap.style.setProperty('--s', s.toFixed(4));
  }
}
async function urlOK(u) {
  try { const r = await fetch(u, { method: 'HEAD', cache: 'no-store' }); return r.ok; } catch { return false; }
}
async function checkApp() {
  if (device.started || !WIDE.matches) return;
  if (!(await urlOK('/app/'))) return;            // not deployed yet: keep the calm waiting state, retry in 30 s
  device.started = true; clearInterval(device.timer);
  const fr = $('#app-frame'), d = $('#device');
  fr.addEventListener('load', () => {
    d.dataset.state = 'live';
    // Presenter clickers send PageUp/PageDown: those change slides even while the phone has focus.
    // Arrow keys stay inside the app (map); click outside the phone to step slides with arrows.
    try {
      fr.contentWindow.addEventListener('keydown', e => {
        if (!isDeck()) return;
        if (e.key === 'PageDown') { e.preventDefault(); go(currentSlide() + 1); }
        else if (e.key === 'PageUp') { e.preventDefault(); go(currentSlide() - 1); }
      });
    } catch { /* same-origin, so this does not throw */ }
  }, { once: true });
  fr.src = APP_EMBED_URL;
}
async function initDevice() {
  if (!$('.device-wrap')) return;
  fitDevice();
  addEventListener('resize', fitDevice);
  if ('ResizeObserver' in window) new ResizeObserver(fitDevice).observe(document.body);
  checkApp(); device.timer = setInterval(checkApp, 30000);
  WIDE.addEventListener?.('change', () => { fitDevice(); checkApp(); });
  // Slide 9: "Watch on a real phone" only exists once the recording does
  if (await urlOK('/home/media/app.mp4')) {
    const t = $('#app-toggle'), d = $('#device-poster'), v = $('#app-video');
    t.hidden = false;
    $$('button', t).forEach(b => b.addEventListener('click', () => {
      const rec = b.dataset.mode === 'rec';
      d.dataset.state = rec ? 'rec' : 'poster';
      $$('button', t).forEach(x => x.setAttribute('aria-pressed', String(x === b)));
      if (rec) { if (!v.src) { v.src = v.dataset.src; v.load(); } v.play?.().catch(() => {}); } else v.pause?.();
    }));
  }
}

/* ---------------- QR ---------------- */
function initQR() {
  const a = $('#app-url'); if (a) { a.href = APP_INSTALL_URL; a.textContent = APP_INSTALL_URL.replace(/^https?:\/\//, '').replace(/\/$/, ''); }
  const box = $('#qr'); if (!box || typeof qrcode !== 'function') return;
  const qr = qrcode(0, 'M'); qr.addData(APP_INSTALL_URL); qr.make();
  box.innerHTML = qr.createSvgTag({ cellSize: 4, margin: 8, scalable: true });
  const s = box.querySelector('svg'); if (s) { s.setAttribute('role', 'img'); s.setAttribute('aria-label', 'QR code for ' + APP_INSTALL_URL); }
}

/* ---------------- deck mode: ?deck or D; arrows / PageUp / PageDown / Space step one slide ---------------- */
const isDeck = () => document.documentElement.classList.contains('deck');
const slides = () => $$('.slide');
function currentSlide() {
  const mid = innerHeight / 2; let idx = 0;
  slides().forEach((s, i) => { const r = s.getBoundingClientRect(); if (r.top <= mid) idx = i; });
  return idx;
}
function go(i) {
  const ss = slides(); i = Math.max(0, Math.min(ss.length - 1, i));
  ss[i].scrollIntoView({ behavior: reduceMotion.matches ? 'auto' : 'smooth', block: 'start' });
}
function updateDeckbar() {
  if (!isDeck()) return;
  const ss = slides(), i = currentSlide();
  $('#deck-count').textContent = `${i + 1} / ${ss.length}`;
  $('#deck-title').textContent = ss[i].dataset.title || '';
}
function toggleDeck(on) {
  const i = currentSlide();
  document.documentElement.classList.toggle('deck', on);
  const u = new URL(location.href);
  u.searchParams.delete('scroll');
  if (on) u.searchParams.set('deck', ''); else u.searchParams.delete('deck');
  history.replaceState(null, '', u.toString().replace(/deck=(?=&|$|#)/, 'deck'));
  if (on && live.ok === false) setEmbedMode('rec', true);
  dispatchEvent(new Event('scroll'));
  requestAnimationFrame(() => { slides()[i].scrollIntoView({ block: 'start' }); updateDeckbar(); fitEmbed(); fitDevice(); });
}
function initDeck() {
  addEventListener('keydown', e => {
    if (e.metaKey || e.ctrlKey || e.altKey || /input|textarea|select/i.test(e.target.tagName)) return;
    if (e.key === 'd' || e.key === 'D') { toggleDeck(!isDeck()); return; }
    if (!isDeck()) return;
    if (['ArrowDown', 'ArrowRight', 'PageDown', ' '].includes(e.key)) { e.preventDefault(); go(currentSlide() + 1); }
    else if (['ArrowUp', 'ArrowLeft', 'PageUp'].includes(e.key)) { e.preventDefault(); go(currentSlide() - 1); }
    else if (e.key === 'Home') { e.preventDefault(); go(0); }
    else if (e.key === 'End') { e.preventDefault(); go(slides().length - 1); }
  });
  addEventListener('scroll', () => requestAnimationFrame(updateDeckbar), { passive: true });
  if (isDeck()) updateDeckbar();
}

/* ---------------- boot ---------------- */
// A bug in one block must never leave the page blank: reveal first, isolate every block.
initReveal();
for (const f of [timeline, aucTable, coldChart, ranges, initQR, initDevice, initEmbed, initDeck]) {
  try { f(); } catch (e) { console.error(f.name, e); }
}
pollHealth(); pollState();
setInterval(pollHealth, HEALTH_MS);
setInterval(pollState, STATE_MS);
setInterval(() => { if (live.ok) renderLive(); }, 1000);
