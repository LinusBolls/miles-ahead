// Data layer for Tonight's moves: GET /moves + SSE /stream?lite=1 (`moves` snapshots, `park`/`depart` for the faint car layer,
// `counters` for the replay clock, `reset` when the replay restarts). One store `S`, one change signal.

const BASE = new URLSearchParams(location.search).get('api') || '/ops/api';

export const S = {
  mode: 'connecting',     // connecting | sse | polling | offline
  source: 'live',
  snap: null,             // latest /moves snapshot {summary, runs, assigned, tally, agents, skip_reasons, ...}
  model: null,            // /moves model block (TabPFN metrics, live latency, thresholds, value assumptions)
  feed: null,             // replay status or live status
  cars: new Map(),        // vid -> [lat, lon] parked Berlin cars (faint context)
  sim: null,              // { t, at, speed } replay clock
  lastMsgAt: 0,
  error: null,
  seq: 0,                 // increments on every snapshot
  firstSnapAt: 0,         // performance.now() of the first snapshot after (re)connect: no arrival effects before
};

const subs = new Set();
let pending = null;
export function onChange(fn) { subs.add(fn); }
export function emit(what = 'all') {
  if (pending) { pending.add(what); return; }
  pending = new Set([what]);
  requestAnimationFrame(() => { const w = pending; pending = null; subs.forEach(f => f(w)); });
}
const mapSubs = new Set();
export function onMapEvent(fn) { mapSubs.add(fn); }
const mapEvent = (t, d) => mapSubs.forEach(f => { try { f(t, d); } catch (e) { console.warn(e); } });

async function getJSON(url, ms = 8000) {
  const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), ms);
  try {
    const r = await fetch(url, { signal: ctl.signal, headers: { Accept: 'application/json' } });
    if (!r.ok) throw new Error(`${r.status} ${url}`);
    return await r.json();
  } finally { clearTimeout(t); }
}
async function post(url, body) {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: body ? JSON.stringify(body) : undefined });
  const j = await r.json().catch(() => null);
  if (!r.ok) throw new Error(j?.detail || `HTTP ${r.status}`);
  return j;
}

function noteClock(c) {
  if (c?.sim_time) S.sim = { t: Date.parse(c.sim_time), at: Date.now(), speed: c.clock_speed || 1 };
  else if (S.source !== 'replay') S.sim = null;
}
function applySnap(snap) {
  S.snap = snap; S.seq++; S.lastMsgAt = Date.now();
  if (!S.firstSnapAt) S.firstSnapAt = performance.now();
  if (snap.clock) noteClock(snap.clock);
}

let es = null, pollT = null, retryT = null, slowT = null;
function stopAll() {
  if (es) { es.close(); es = null; }
  clearInterval(pollT); clearTimeout(retryT); clearInterval(slowT);
  pollT = retryT = slowT = null;
}

export async function connect(source = S.source) {
  stopAll();
  S.source = source; S.mode = 'connecting'; S.error = null; S.snap = null; S.firstSnapAt = 0; S.cars = new Map();
  emit('mode');
  try {
    const m = await getJSON(`${BASE}/moves?source=${source}`);
    S.model = m.model; S.feed = m.replay || m.live || null;
    applySnap(m);
    loadCars();
    startSSE();
    slowT = setInterval(refreshModel, 60000);
    emit('all');
  } catch (e) {
    S.error = String(e.message || e); S.mode = 'offline'; emit('all');
    retryT = setTimeout(() => connect(S.source), 20000);
  }
}
export async function refreshModel() {
  try { const m = await getJSON(`${BASE}/moves?source=${S.source}`); S.model = m.model; S.feed = m.replay || m.live || null; applySnap(m); emit('all'); } catch {}
}
async function loadCars() {
  try {
    const r = await getJSON(`${BASE}/cars?source=${S.source}`, 10000);
    S.cars = new Map((r.cars || []).map(([vid, lat, lon]) => [vid, [lat, lon]]));
    emit('cars');
  } catch {}
}

function startSSE() {
  if (!('EventSource' in window)) return startPolling();
  let errors = 0;
  es = new EventSource(`${BASE}/stream?source=${S.source}&lite=1`);
  es.onopen = () => { S.mode = 'sse'; errors = 0; S.lastMsgAt = Date.now(); emit('mode'); };
  const parse = ev => { try { return JSON.parse(ev.data); } catch { return null; } };
  es.addEventListener('moves', ev => { const d = parse(ev); if (d) { applySnap(d); emit('moves'); } });
  es.addEventListener('counters', ev => { const c = parse(ev); if (c) { noteClock(c); S.lastMsgAt = Date.now(); emit('clock'); } });
  es.addEventListener('park', ev => {
    const d = parse(ev); if (!d) return; S.lastMsgAt = Date.now();
    if (!d.test) S.cars.set(d.vid, [d.lat, d.lon]);
    emit('cars');
  });
  es.addEventListener('depart', ev => { const d = parse(ev); if (!d) return; S.cars.delete(d.vid); mapEvent('depart', d); emit('cars'); });
  es.addEventListener('reset', () => { S.firstSnapAt = 0; refreshModel().then(loadCars); });
  es.addEventListener('ping', () => { S.lastMsgAt = Date.now(); });
  es.onerror = () => {
    errors++;
    if (es && (es.readyState === EventSource.CLOSED || errors >= 3)) {
      es.close(); es = null; startPolling();
      retryT = setTimeout(() => { if (S.mode === 'polling') { clearInterval(pollT); startSSE(); } }, 60000);
    }
  };
}
function startPolling() {
  S.mode = 'polling'; emit('mode');
  clearInterval(pollT);
  pollT = setInterval(async () => {
    try { const m = await getJSON(`${BASE}/moves?source=${S.source}`); S.model = m.model; applySnap(m); S.mode = 'polling'; emit('moves'); }
    catch (e) { S.error = String(e.message || e); S.mode = 'offline'; stopAll(); emit('all'); retryT = setTimeout(() => connect(S.source), 20000); }
  }, 5000);
}

// ---------- actions ----------
export async function assignRun(moveIds, agent, operator, runId, channel) {
  const r = await post(`${BASE}/moves/assign`, { move_ids: moveIds, agent, operator, run_id: runId, channel });
  return r;
}
export const skipMove = (moveId, reason, operator) => post(`${BASE}/moves/skip`, { move_id: moveId, reason, operator });
export const loadDetail = id => getJSON(`${BASE}/moves/${encodeURIComponent(id)}`, 6000);
export async function setSpeed(speed) {
  const st = await post(`${BASE}/replay/speed?speed=${speed}`);
  S.feed = st; if (S.sim) S.sim = { t: Date.parse(st.data_time), at: Date.now(), speed: st.speed };
  emit('clock'); emit('mode');
  return st;
}
export const qaInject = kind => post(`${BASE}/qa/inject?kind=${encodeURIComponent(kind)}&source=${S.source}`);
export const qaClear = () => post(`${BASE}/qa/clear?source=${S.source}`);
export const simNow = () => (S.sim ? S.sim.t + (Date.now() - S.sim.at) * S.sim.speed : Date.now());
