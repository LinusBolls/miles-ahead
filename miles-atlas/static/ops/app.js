import { S, onChange, onMapEvent, connect, refreshModel, assignRun, skipMove, loadDetail, setSpeed, qaInject, qaClear, simNow } from './api.js';
import * as M from './map.js';
const { esc } = M;

const $ = s => document.querySelector(s);
const TZ = 'Europe/Berlin';
const hhmm = new Intl.DateTimeFormat('en-GB', { timeZone: TZ, hour: '2-digit', minute: '2-digit' });
const dayFmt = new Intl.DateTimeFormat('en-GB', { timeZone: TZ, weekday: 'short', day: 'numeric', month: 'short' });
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)');
const eur = v => (v == null || !Number.isFinite(+v) ? '–' : '€' + Math.round(+v).toLocaleString('en-GB'));
const eurK = v => (v >= 10000 ? `€${Math.round(v / 1000)}k` : v >= 1000 ? `€${(v / 1000).toFixed(1)}k` : eur(v));
const pct = x => (x == null ? '–' : `${Math.round(x * 100)}%`);
const SUB = { strand: 'Relocate', active: 'Clear', soon: 'Clear', far: 'Clear' };
const runLabel = r => `${r.kind === 'relocate' ? 'relocation' : 'clear'} run ${r.rank}`;
const RIDER_AGENT = 'Rider app';
// move cost per channel: assumptions, served by the API (summary.costs) so UI and ranking agree
const costs = () => S.snap?.summary?.costs || { crew_eur: 20, rider_eur: 5 };
const signed = v => (v < 0 ? '−' : '') + eur(Math.abs(v));
const clsWord = c => (c === 'van' ? 'vans' : 'cars');
function netDef(m) {
  const c = costs(), g = m.value_eur;
  const what = m.value_kind === 'exposure' ? 'exposure (fine + admin + tow risk)' : m.kind === 'relocate' ? 'model value (idle hours avoided × €1.36)' : 'expected tow cost avoided';
  const line = m.channel === 'rider'
    ? `${eur(g)} ${what} − €${c.rider_eur} rider credit = ${signed(m.net_rider_eur)} net. A crew trip (~€${c.crew_eur}) would net ${signed(m.net_crew_eur)}, so this goes to riders.`
    : `${eur(g)} ${what} − ~€${c.crew_eur} crew trip = ${signed(m.net_crew_eur)} net.`;
  return `${line} Move costs are assumptions (crew €${c.crew_eur}, rider €${c.rider_eur}).`;
}

// ---------- UI state ----------
const U = { sel: null, drawer: false, detail: null, detailFor: null, seen: new Set(), entered: new Map(), qa: false, pick: null, assignedOpen: true, clrOpen: false };
let opName = 'Head of Ops';
try { opName = localStorage.getItem('milesops.operator') || opName; } catch {}
let lastAgent = null;
try { lastAgent = localStorage.getItem('milesops.agent'); } catch {}

// ---------- derived ----------
const runs = () => S.snap?.runs || [];
const assigned = () => S.snap?.assigned || [];
const openMoves = () => runs().flatMap(r => r.moves);
const allMoves = () => [...openMoves(), ...assigned().flatMap(r => r.moves)];
const findMove = id => allMoves().find(m => m.id === id);
const runOf = id => runs().find(r => r.moves.some(m => m.id === id)) || assigned().find(r => r.moves.some(m => m.id === id));
const isOpen = id => openMoves().some(m => m.id === id);

// ---------- header ----------
function renderHeader() {
  const s = S.snap?.summary;
  const h = $('#headline');
  if (!s) { h.textContent = S.mode === 'offline' ? 'API offline' : '–'; h.dataset.def = ''; return; }
  h.innerHTML = `<b class="n">${s.relocate}</b> to relocate<span class="sep">,</span> <b class="n">${s.clear}</b> to clear`;
  h.dataset.def = `Open moves right now. Relocations are cars TabPFN expects to sit idle more than 12 h; clears are cars in, or about to be in, a no-parking window, or far from legal parking. ${s.act_now} clears have a clock running.`;
}
function renderMode() {
  document.querySelectorAll('#source button').forEach(b => { const on = b.dataset.src === S.source; b.classList.toggle('on', on); b.setAttribute('aria-pressed', on); });
  const sp = $('#speed');
  sp.hidden = !(S.source === 'replay' && (S.mode === 'sse' || S.mode === 'polling'));
  const cur = S.sim?.speed ?? S.feed?.speed;
  sp.querySelectorAll('button').forEach(b => { const on = +b.dataset.speed === cur; b.classList.toggle('on', on); b.setAttribute('aria-pressed', on); });
  renderStatus(); renderQA();
}
let lastStatus = '';
function renderStatus() {
  const el = $('#status');
  let cls = '', txt = 'Connecting', def = 'Connecting to the ops API.';
  const since = S.lastMsgAt ? (Date.now() - S.lastMsgAt) / 1000 : null;
  if (S.mode === 'offline') { cls = 'off'; txt = 'API offline'; def = `The ops API did not answer (${S.error || 'no response'}). Retrying every 20 s.`; }
  else if (S.mode === 'sse' || S.mode === 'polling') {
    if (S.source === 'replay') { cls = 'replay'; txt = 'Replay, June 2024'; def = `Replay of real Berlin ride ends, June 3–22 2024, at ${S.sim?.speed ?? '–'}×, daytime only. Not live data. TabPFN scores were computed once, offline, out-of-sample.`; }
    else if (S.feed?.status === 'stale') { cls = 'stale'; txt = 'Live feed stale'; def = S.feed.message || 'No fresh Berlin data.'; }
    else { cls = since != null && since < 40 ? 'live' : 'stale'; txt = 'Live'; def = 'Live Berlin data from the MILES app API, scored as it arrives (TabPFN micro-batch every 60 s).'; }
  }
  if (cls + txt !== lastStatus) { el.className = 'pill ' + cls; el.innerHTML = `<i></i><span>${txt}</span>`; lastStatus = cls + txt; }
  el.dataset.def = def;
}
function tickClock() {
  const t = new Date(S.source === 'replay' && S.sim ? simNow() : Date.now());
  $('#clock').innerHTML = `${hhmm.format(t)}<span>${dayFmt.format(t)}${S.source === 'replay' ? ' 2024' : ''}</span>`;
  const hr = +hhmm.format(t).slice(0, 2), title = hr >= 17 || hr < 5 ? "Tonight's moves" : "Today's moves";
  const bt = $('.brand b'); if (bt && bt.textContent !== title) { bt.textContent = title; document.title = title; }
  renderStatus();
}

// ---------- list ----------
const animatedRows = new Set();
function moveRow(m, i, run) {
  const sel = m.id === U.sel;
  const fresh = U.entered.has(m.id) && performance.now() - U.entered.get(m.id) < 2500 && !animatedRows.has(m.id);
  if (fresh) animatedRows.add(m.id);
  const to = m.to ? esc(m.to.street) : '<span class="dim">no target</span>';
  const right = m.status === 'assigned' ? outcomeHTML(m.outcome)
    : m.sub === 'soon' ? `<span class="dl">before ${esc(m.deadline)}</span>`
    : m.sub === 'active' ? '<span class="dl">now</span>'
    : `<span class="age">${ageTxt(m.age_min)}</span>`;
  const valDef = m.net_eur != null ? netDef(m) : m.value_kind === 'exposure' ? 'Exposure: fine + MILES admin fee + tow cost × observed tow rate. What is at risk, not an expected cost.'
    : m.kind === 'relocate' ? 'Expected idle hours avoided × €1.36 per car-hour (model-based).' : 'Observed tow rate × tow cost (fine not counted: no definite violation).';
  return `<div class="mv${sel ? ' sel' : ''}${m.act_now ? ' act' : ''}${fresh ? ' enter' : ''}" role="option" aria-selected="${sel}" data-id="${esc(m.id)}">
    <span class="num n">${run ? i + 1 : ''}</span>
    <span class="plate">${esc(m.plate || '••')}</span>
    <span class="route"><span class="fr">${esc(m.from.street || 'unknown street')}</span><span class="ar" aria-hidden="true">→</span><span class="to">${to}</span></span>
    <span class="val ${m.value_kind}" data-def="${esc(valDef)}">${m.net_eur != null ? signed(m.net_eur) : eur(m.value_eur)}</span>
    <span class="kind ${m.kind}${m.act_now ? ' act' : ''}">${SUB[m.sub]}</span>
    <span class="why">${whyHTML(m)}${m.test ? ' <span class="tag" data-def="QA test move: injected by hand, not real data. Never scored or tallied.">test</span>' : ''}</span>
    <span class="rt">${right}</span>
  </div>`;
}
function whyHTML(m) {
  if (m.kind !== 'relocate') return esc(m.reason);
  const extra = m.reason && !/^idle risk/.test(m.reason) ? ` · ${esc(m.reason)}` : '';
  const by = m.test ? 'test' : m.scorer === 'TabPFN' ? 'TabPFN' : 'GBM fallback';
  const def = m.test ? 'QA test move: the probability is made up.' : `${by} probability that this car sits idle more than 12 h, scored when the ride ended.${m.scorer === 'TabPFN' ? '' : ' TabPFN did not answer in time, so the gradient-boosting model scored it.'}`;
  return `<b class="pp n" data-def="${def}">${pct(m.p)}</b> idle >12 h${m.scorer !== 'TabPFN' && !m.test ? ' · GBM fallback' : ''}${extra}`;
}
const ageTxt = m => (m == null ? '' : m < 1 ? 'just now' : m < 60 ? `${m} min ago` : `${Math.floor(m / 60)} h ${m % 60} min ago`);
function outcomeHTML(o) {
  if (!o) return '';
  return `<span class="oc ${o.state}"><i></i>${esc(o.text)}</span>`;
}
function runHead(r) {
  const flag = r.active ? '<span class="dl">act now</span>' : r.deadline ? `<span class="dl">before ${esc(r.deadline)}</span>` : '';
  return `<div class="run-h${r.urgent ? ' act' : ''}" data-run="${esc(r.id)}">
    <b>Run ${r.rank}</b><span class="rn">${esc(r.name)}</span>
    <span class="meta"><b class="n">${r.n}</b> car${r.n === 1 ? '' : 's'}</span><span class="meta" data-def="Estimated minutes for one agent: driving each car to its target at 18 km/h + 4 min to park, and riding between cars at 13 km/h. Excludes getting to the first car.">~<b class="n">${r.minutes}</b> min</span>
    ${flag}<span class="rv n" data-def="Net for this run: each car's value minus ~€${costs().crew_eur} crew cost per car (assumed).">${eur(r.net_eur ?? r.value_eur)}</span>
    <button class="btn sm as" data-assign="${esc(r.id)}" title="Assign this run to a field agent">Assign <kbd>a</kbd></button>
  </div>`;
}
function assignedHead(r) {
  return `<div class="run-h done" data-run="${esc(r.id)}">
    <b>${esc(r.agent || 'Agent')}</b><span class="rn">${esc(r.name)}</span>
    <span class="meta"><b class="n">${r.n}</b> car${r.n === 1 ? '' : 's'}</span><span class="meta"><b class="n">${r.done}</b> of ${r.n} checked</span><span class="rv n">${eur(r.net_eur ?? r.value_eur)}</span>
  </div>`;
}
let lastListKey = '';
function renderList(force) {
  const s = S.snap;
  const el = $('#list');
  const bh = $('#boardH');
  if (!s) {
    bh.innerHTML = '';
    el.innerHTML = S.mode === 'offline'
      ? `<div class="empty"><p>The ops API is not answering, so there are no moves to show.</p><button class="btn" id="retry">Retry</button></div>`
      : '<div class="empty"><p>Loading moves</p></div>';
    $('#retry')?.addEventListener('click', () => connect(S.source));
    lastListKey = ''; return;
  }
  const rs = runs(), as = assigned();
  const key = S.seq + '|' + U.sel + '|' + U.assignedOpen;
  if (!force && key === lastListKey) return;
  lastListKey = key;
  bh.hidden = true;
  const rel = rs.filter(r => r.kind === 'relocate'), clr = rs.filter(r => r.kind !== 'relocate');
  const nRel = rel.reduce((a, r) => a + r.n, 0), nClr = clr.reduce((a, r) => a + r.n, 0);
  const hid = s.summary?.hidden_low_value || 0;
  const c = costs();
  const runHTML = r => `<section class="run${r.urgent ? ' act' : ''}">${runHead(r)}${r.moves.map((m, i) => moveRow(m, i, r)).join('')}</section>`;
  const riderDef = `Worth moving, but not worth a crew trip (~€${c.crew_eur}, assumed). Offered to customers instead: €${c.rider_eur} credit for moving the car (assumed). One car per rider. € = value − €${c.rider_eur}.`;
  const riderHTML = (rr, kind) => !rr.length ? '' : `<div class="sec-h rider" data-def="${riderDef}">Rider rescue <b class="n">${rr.reduce((a, r) => a + r.n, 0)}</b><span>€${c.rider_eur} credit each, one car per rider</span></div>` + rr.flatMap(r => r.moves).map(m => moveRow(m, 0, null)).join('');
  const relCrew = rel.filter(r => r.channel !== 'rider'), relRider = rel.filter(r => r.channel === 'rider');
  const clrCrew = clr.filter(r => r.channel !== 'rider'), clrRider = clr.filter(r => r.channel === 'rider');
  let a = `<p class="costs" data-def="Every € in the list is net: the move's value minus what the move costs. A move goes to the crew only if it nets at least €1 after a crew trip; otherwise to riders if it nets at least €1 after the credit; otherwise it is not listed. Both costs are our assumptions, not MILES figures.">€ = net of move cost · crew €${c.crew_eur} · rider €${c.rider_eur}, assumed</p>`;
  a += `<div class="pane rel"><div class="pane-h"><b>Relocate</b><span class="n">${nRel}</span><span class="sub" data-def="Cars TabPFN expects to sit idle more than 12 h, scored when the ride ended, each with a nearby street where rides start. Value compares the same vehicle class (van or car) here and at the target. In our 2024 data, MILES relocations start a median ~25 h after the last ride.">likely idle >12 h, scored by TabPFN at ride end</span></div><div class="pane-b">`;
  a += relCrew.length ? relCrew.map(runHTML).join('')
    : rel.length ? `<p class="none">No relocation pays for a crew trip right now (~€${c.crew_eur}, assumed).</p>`
    : `<div class="empty"><p>No relocations worth a move right now.</p><p class="sub">In our 2024 data, MILES relocations start a median ~25 h after the car's last ride. Cars here are flagged at ride end.</p></div>`;
  a += riderHTML(relRider);
  if (hid) a += `<p class="more" data-def="Not listed: moves that net less than €1 on both channels (${s.summary.hidden_net_negative ?? 0} now), plus anything beyond the 30 best relocations and 12 far-from-legal clears, so the list stays doable.">${hid} move${hid === 1 ? '' : 's'} not listed (net under €1, or beyond the top 30)</p>`;
  a += `</div></div>`;
  let b = `<div class="pane clr${U.clrOpen ? '' : ' shut'}"><button class="pane-h tog" id="clrTog" aria-expanded="${U.clrOpen}" title="${U.clrOpen ? 'Collapse' : 'Show'} the cars to clear"><b>Clear before it costs</b><span class="n">${nClr}</span><span class="sub">${s.summary.act_now ? `<span class="dl">${s.summary.act_now} with a clock running</span>${U.clrOpen ? ', deadlines first' : ''}` : (U.clrOpen ? 'deadlines first' : 'no-parking windows, far from legal parking')}</span><i class="chev" aria-hidden="true">›</i></button><div class="pane-b">`;
  if (U.clrOpen) b += clr.length ? clrCrew.map(runHTML).join('') + riderHTML(clrRider) : `<div class="empty"><p>No cars to clear right now.</p></div>`;
  if (as.length) {
    b += `<button class="sec-h" id="asTog" aria-expanded="${U.assignedOpen}">Assigned today <b class="n">${as.length}</b><span>${U.assignedOpen ? 'Hide' : 'Show'}</span></button>`;
    if (U.assignedOpen) for (const r of as) b += `<section class="run done">${assignedHead(r)}${r.moves.map((m, i) => moveRow(m, i, r)).join('')}</section>`;
  }
  b += `</div></div>`;
  const keep = [...el.querySelectorAll('.pane-b')].map(x => x.scrollTop);
  const html = a + b;
  el.innerHTML = html;
  el.querySelectorAll('.pane-b').forEach((x, k) => { if (keep[k] != null) x.scrollTop = keep[k]; });
  $('#asTog')?.addEventListener('click', () => { U.assignedOpen = !U.assignedOpen; renderList(true); });
  $('#clrTog')?.addEventListener('click', () => { U.clrOpen = !U.clrOpen; renderList(true); });
  const selEl = el.querySelector('.mv.sel');
  if (selEl) { const r = selEl.getBoundingClientRect(), p = selEl.closest('.pane-b').getBoundingClientRect(); if (r.top < p.top + 40 || r.bottom > p.bottom) selEl.scrollIntoView({ block: 'nearest' }); }
}
$('#list').addEventListener('click', e => {
  const b = e.target.closest('[data-assign]');
  if (b) { e.stopPropagation(); const r = runs().find(x => x.id === b.dataset.assign); if (r) { select(r.moves[0].id, { pointer: true, drawer: false }); openAssign(r, b); } return; }
  const row = e.target.closest('.mv');
  if (row) return select(row.dataset.id, { pointer: true, drawer: true });
  const rh = e.target.closest('.run-h');
  if (rh) { const r = runs().find(x => x.id === rh.dataset.run) || assigned().find(x => x.id === rh.dataset.run); if (r) select(r.moves[0].id, { pointer: true, drawer: false }); }
});

const KEYS = '<span class="keys"><kbd>j</kbd><kbd>k</kbd> move <kbd>a</kbd> assign <kbd>s</kbd> skip <kbd>Enter</kbd> details</span>';
function renderTally() { renderTally0(); const el = $('#tally'); if (S.snap) el.insertAdjacentHTML('beforeend', KEYS); }
function renderTally0() {
  const t = S.snap?.tally || {};
  const el = $('#tally');
  const n = t.assigned || 0;
  if (!S.snap) { el.innerHTML = ''; return; }
  if (!n && !t.skipped) { el.innerHTML = '<span>Today: nothing assigned yet. Outcomes are tracked for every assigned move.</span>'; return; }
  const parts = [];
  if (t.rel_good || t.rel_bad) parts.push(`<b class="n">${t.rel_good || 0}</b> relocated rented within 2 h, <b class="n">${t.rel_bad || 0}</b> still idle`);
  if (t.clr_good || t.clr_bad) parts.push(`<b class="n">${t.clr_good || 0}</b> cleared in time, <b class="n">${t.clr_bad || 0}</b> not`);
  const pend = (t.rel_pending || 0) + (t.clr_pending || 0);
  if (pend) parts.push(`<b class="n">${pend}</b> watching`);
  if (t.skipped) parts.push(`<b class="n">${t.skipped}</b> skipped`);
  el.innerHTML = `<span>Today: <b class="n">${n}</b> assigned${parts.length ? '. ' + parts.join('. ') : ''}.${S.source === 'replay' ? ' <span class="dim">Replay outcomes are what the car really did in June 2024.</span>' : ''}</span>`;
}

// ---------- selection + map ----------
function select(id, { pointer = false, drawer } = {}) {
  const m = findMove(id); if (!m) return;
  if (m.kind !== 'relocate' && !U.clrOpen && runs().some(r => r.moves.includes(m))) U.clrOpen = true;
  const prevRun = runOf(U.sel)?.id, hadDrawer = U.drawer;
  U.sel = id;
  if (drawer != null) U.drawer = drawer || (U.drawer && !pointer);
  const r = runOf(id);
  M.setInset(U.drawer ? Math.min(440, $('#map').clientWidth) : 0);
  if (r && (r.id !== prevRun || hadDrawer !== U.drawer)) M.fitRun(r, pointer); else M.panTo(m, pointer);
  syncMap(); renderList(true);
  if (U.drawer) openDrawer(id, pointer);
}
function syncMap() {
  if (!mapReady) return;
  const r = runOf(U.sel);
  const inRun = new Map((r?.moves || []).map((m, i) => [m.id, i + 1]));
  const items = openMoves().map(m => ({ m, n: inRun.get(m.id) || 0, sel: m.id === U.sel, dim: r && !inRun.has(m.id) }));
  if (r && !runs().includes(r)) r.moves.forEach((m, i) => items.push({ m, n: i + 1, sel: m.id === U.sel, dim: false }));
  M.setMoves(items, r);
}

// ---------- detail drawer ----------
async function openDrawer(id, animate) {
  const d = $('#drawer');
  const wasHidden = d.hidden;
  U.drawer = true;
  if (U.detailFor !== id) { U.detail = null; U.detailFor = id; }
  renderDrawer();
  if (wasHidden && animate && !reduceMotion.matches) { d.classList.remove('opening'); void d.offsetWidth; d.classList.add('opening'); }
  try {
    const det = await loadDetail(id);
    if (U.detailFor === id) { U.detail = det; renderDrawer(); }
  } catch { if (U.detailFor === id) { U.detail = { error: true }; renderDrawer(); } }
}
function closeDrawer() { U.drawer = false; $('#drawer').hidden = true; M.setInset(0); }
function renderDrawer() {
  const el = $('#drawer');
  const m = findMove(U.sel);
  if (!U.drawer || !m) { el.hidden = true; return; }
  el.hidden = false;
  const d = U.detail;
  const open = isOpen(m.id);
  let why = '<p class="dim">Loading</p>';
  if (d?.error) why = '<p class="dim">Details could not be loaded.</p>';
  else if (d && d.kind === 'relocate' && m.test) {
    why = `<div class="big"><b class="n">${pct(d.model?.p)}</b> made-up idle risk</div><p>QA test move: injected by hand to check the list, the drawer and the map. No model scored it and it is never tallied.</p>`;
  } else if (d && d.kind === 'relocate') {
    const md = d.model || {}, c = md.calibration, inp = md.inputs || {};
    const scorer = md.name === 'TabPFN' ? 'TabPFN' : md.name === 'test' ? 'test event' : 'GBM fallback';
    why = `<div class="big"><b class="n">${pct(md.p)}</b> chance this car sits idle more than 12 h</div>
      <p>${c ? `Of ride ends ${scorer === 'TabPFN' ? 'TabPFN' : 'the GBM'} scored ${pct(c.lo)}–${pct(c.hi)}, <b>${pct(c.rate)}</b> really sat more than 12 h (${c.n.toLocaleString('en-GB')} ride ends, ${scorer === 'TabPFN' ? 'June 17–22 2024, out-of-sample' : 'in-sample'}).` : ''}</p>
      <p class="dim">Scored by <b>${scorer}</b>${md.name === 'TabPFN' ? ` against 10k Berlin ride ends (June 3–16 2024) as context, AUC ${md.auc}` : ''}. Moves start at p ≥ ${pct(md.threshold)}.${S.source === 'live' ? ' Live ride ends are from 2026 and the context from 2024, so read the percentage as approximate; the ranking is the reliable part.' : ''}</p>
      <dl class="kv">${inp.hour != null ? `<dt>Ride end</dt><dd>${esc(inp.weekday || '')} ${String(inp.hour).padStart(2, '0')}:00</dd>` : ''}${inp.km_from_centre != null ? `<dt>From centre</dt><dd class="n">${inp.km_from_centre} km</dd>` : ''}${inp.charge != null ? `<dt>Charge</dt><dd class="n">${inp.charge}%</dd>` : ''}${inp.car ? `<dt>Car</dt><dd>${esc(inp.car)}${inp.size ? ` (${esc(inp.size)})` : ''}</dd>` : ''}</dl>`;
  } else if (d) {
    const r = d.restriction || {};
    why = m.sub === 'far'
      ? `<div class="big"><b class="n">${Math.round(r.dist_to_legal_m || 20)} m</b> from the nearest legal street parking</div><p>Inside the S-Bahn ring and not in a car park. Cars parked like this were moved without a customer ride 2.3× as often (3.2% vs 1.4%), a tow or Umsetzung proxy.</p>`
      : `<div class="big">${esc(r.label || 'Restriction')}${m.sub === 'soon' ? ` starts <b class="n">${esc(r.deadline || m.deadline)}</b>` : ' active now'}</div>
         <p>${esc(r.label || '')}, ${esc(r.hours || 'always')}${r.reason && r.reason !== r.label ? ` (${esc(r.reason)})` : ''}, ${esc(r.street || m.from.street)}. ${m.sub === 'soon' ? 'Parked legally now; it becomes a violation when the window opens.' : 'Parked inside an active no-parking window.'}</p>`;
  }
  let where = '';
  if (d?.target) {
    const t = d.target;
    where = `<h3>Where to</h3><p><b>${esc(t.street)}</b>, ${t.km} km away${t.zone ? `, ${esc(t.zone)}` : ''}.</p>
      <dl class="kv"><dt>Ride starts expected</dt><dd class="n">${t.expected_starts_3h} in the next 3 h</dd><dt>Idle cars there now</dt><dd class="n">${t.idle_now}</dd><dt>Typical idle there</dt><dd class="n">${t.typical_idle_h} h for ${clsWord(t.vclass)} at this hour${t.vclass === 'van' && t.typical_idle_all_h != null ? ` <span class="dim">(all vehicles ${t.typical_idle_all_h} h)</span>` : ''}</dd></dl>
      <p class="dim">Demand: customer ride starts per 400 m cell and hour of week, Berlin June 3–16 2024.</p>`;
  } else if (m.to) where = `<h3>Where to</h3><p>Nearest legal spot: <b>${esc(m.to.street)}</b>, ${m.to.km} km.</p>`;
  let val = '';
  if (d?.value) {
    const v = d.value;
    val = v.kind === 'expected' && d.kind === 'relocate'
      ? `<h3>Worth</h3><p class="calc n">${v.e_idle_here_h} h expected idle here − ${v.idle_target_h} h typical for ${clsWord(v.vclass)} at the target = ${v.avoided_h} h × €${v.eur_per_car_h.toFixed(2)} = ${eur(v.eur)} value</p>${netHTML(v)}
         <p class="dim">€1.36 per car-hour = MILES 2024 audited revenue €227M / ~19k cars / 8,760 h. Expected idle here = p × ${v.h_strand} h + (1 − p) × ${v.h_no_strand} h (mean idle of stranded and other Berlin ${v.vclass === 'van' ? 'van' : 'car'} ride ends, June 2024). Both sides use the same vehicle class, so vans are compared with vans.</p>`
      : m.sub === 'far'
      ? `<h3>Worth</h3><p class="calc n">3.2% tow rate × (€${v.tow_fee} Umsetzung + €${v.admin_tow} MILES admin) = ${eur(v.eur)} expected</p>${netHTML(v)}<p class="dim">A fine (€25–55, BKatV) is possible but not counted: there is no definite violation.</p>`
      : `<h3>Exposure</h3><p class="calc n">€${v.fine} fine + €${v.admin_fine.toFixed(2)} MILES admin + ${(v.p_tow * 100).toFixed(1)}% tow rate × (€${v.tow_fee} + €${v.admin_tow}) = ${eur(v.eur)}</p>${netHTML(v)}
         <p class="dim">Fine per BKatV, Umsetzung up to €225 (service.berlin.de), MILES admin fees €29.50 per fine and €70 per tow. The tow rate is observed (${esc(v.p_tow_basis)}); whether a ticket is issued is not, so this is exposure, not an expected cost.</p>`;
  }
  const r = runOf(m.id);
  const act = open && m.channel === 'rider'
    ? `<div class="acts"><button class="btn primary" id="dOffer" data-def="Records the rider offer for this car and tracks the outcome like any assignment. Sending it to the rider app from this console is not wired yet.">Offer to riders, €${costs().rider_eur} <kbd>a</kbd></button><button class="btn" id="dSkip">Skip this car <kbd>s</kbd></button></div>`
    : open
    ? `<div class="acts"><button class="btn primary" id="dAssign">Assign ${r ? runLabel(r) : 'run'} <kbd>a</kbd></button><button class="btn" id="dSkip">Skip this car <kbd>s</kbd></button></div>`
    : m.status === 'assigned' ? `<div class="acts"><p>Assigned to <b>${esc(m.agent || '')}</b>. ${outcomeHTML(m.outcome)}</p></div>` : '';
  el.innerHTML = `
    <div class="d-top"><span class="kind ${m.kind}${m.act_now ? ' act' : ''}">${SUB[m.sub]}</span><span class="plate">${esc(m.plate)}</span><span class="dim">${esc(m.car || '')}</span>${m.test ? '<span class="tag">test</span>' : ''}<button class="x" id="dClose" aria-label="Close">Close <kbd>Esc</kbd></button></div>
    <h2>${esc(m.from.street || 'Unknown street')}${m.to ? ` <span class="ar">→</span> ${esc(m.to.street)}` : ''}</h2>
    <p class="sub">${esc(m.reason)}${m.deadline ? `, move before ${esc(m.deadline)}` : ''}. ${m.net_eur != null ? `${signed(m.net_eur)} net, ${m.channel === 'rider' ? `rider rescue (€${costs().rider_eur})` : `crew (~€${costs().crew_eur})`}` : `${eur(m.value_eur)} ${m.value_kind === 'exposure' ? 'exposure' : 'expected'}`}.</p>
    ${act}
    <h3>Why</h3>${why}${where}${val}`;
  $('#dClose').onclick = closeDrawer;
  $('#dAssign')?.addEventListener('click', e => { const rr = runOf(m.id); if (rr) openAssign(rr, e.currentTarget); });
  $('#dOffer')?.addEventListener('click', () => offerRider(m));
  $('#dSkip')?.addEventListener('click', e => openSkip(m, e.currentTarget));
}

function netHTML(v) {
  if (v.net_crew_eur == null) return '';
  const rider = v.channel === 'rider';
  return `<p class="calc n">${rider ? `${eur(v.eur)} − €${v.rider_eur} rider credit = <b>${signed(v.net_rider_eur)} net</b>, rider rescue. A crew trip (~€${v.crew_eur}) would net ${signed(v.net_crew_eur)}.`
    : `${eur(v.eur)} − ~€${v.crew_eur} crew trip = <b>${signed(v.net_crew_eur)} net</b>, crew move.`}</p>
    <p class="dim">Move costs are assumptions, not MILES figures: a crew trip ~€${v.crew_eur} (staff time and getting there), a rider rescue the €${v.rider_eur} credit we pay.</p>`;
}
async function offerRider(m) {
  const r = runOf(m.id); if (!r) return;
  const idx = openMoves().findIndex(x => x.id === m.id);
  try {
    await assignRun(r.moves.map(x => x.id), RIDER_AGENT, opName, r.id, 'rider');
    toast(`Offered ${m.plate} to riders`, `€${costs().rider_eur} credit, ${signed(m.net_eur)} net. Outcome is tracked; the push to the rider app is not sent from this console yet.`);
    advanceAfter(r.moves.map(x => x.id), idx);
    await refreshModel();
  } catch (e) { toast(`Not recorded: ${e.message}`, null); }
}

// ---------- assign / skip pickers (number keys pick, Esc closes) ----------
function placePick(anchor) {
  const p = $('#pick');
  const r = anchor?.getBoundingClientRect?.() || { left: innerWidth / 2 - 130, bottom: innerHeight / 3, top: innerHeight / 3 };
  p.hidden = false;
  const w = p.offsetWidth, h = p.offsetHeight;
  let top = r.bottom + 6, up = false;
  if (top + h > innerHeight - 8) { top = r.top - h - 6; up = true; }
  p.style.left = Math.max(8, Math.min(innerWidth - w - 8, r.left)) + 'px';
  p.style.top = top + 'px';
  p.style.transformOrigin = up ? 'bottom left' : 'top left';
  if (!reduceMotion.matches && !U.pickKeyboard) { p.classList.remove('opening'); void p.offsetWidth; p.classList.add('opening'); } else p.classList.remove('opening');
}
function openAssign(r, anchor) {
  const agents = S.snap?.agents || [];
  const order = lastAgent && agents.includes(lastAgent) ? [lastAgent, ...agents.filter(a => a !== lastAgent)] : agents;
  U.pick = { type: 'assign', run: r, options: order };
  $('#pick').innerHTML = `<div class="ph">Assign ${runLabel(r)}, ${r.n} car${r.n === 1 ? '' : 's'}, ~${r.minutes} min</div>
    ${order.map((a, i) => `<button class="opt" data-i="${i}"><kbd>${i + 1}</kbd>${esc(a)}${a === lastAgent ? '<span class="dim">last used</span>' : ''}</button>`).join('')}`;
  placePick(anchor || document.querySelector(`[data-assign="${CSS.escape(r.id)}"]`));
}
function openSkip(m, anchor) {
  const reasons = S.snap?.skip_reasons || ['Not worth the trip'];
  U.pick = { type: 'skip', move: m, options: reasons };
  $('#pick').innerHTML = `<div class="ph">Skip ${esc(m.plate)}: why?</div>
    ${reasons.map((x, i) => `<button class="opt" data-i="${i}"><kbd>${i + 1}</kbd>${esc(x)}</button>`).join('')}`;
  placePick(anchor || document.querySelector(`.mv[data-id="${CSS.escape(m.id)}"]`));
}
function closePick() { U.pick = null; $('#pick').hidden = true; U.pickKeyboard = false; }
async function choosePick(i) {
  const p = U.pick; if (!p || p.options[i] == null) return;
  const choice = p.options[i];
  closePick();
  try {
    if (p.type === 'assign') {
      const ids = p.run.moves.map(m => m.id);
      const idx = openMoves().findIndex(m => m.id === U.sel);
      await assignRun(ids, choice, opName, p.run.id);
      lastAgent = choice; try { localStorage.setItem('milesops.agent', choice); } catch {}
      toast(`${runLabel(p.run).replace(/^./, c => c.toUpperCase())} assigned to ${choice}`, `${p.run.n} car${p.run.n === 1 ? '' : 's'}, ~${p.run.minutes} min, ${eur(p.run.value_eur)}. Outcomes are tracked automatically.`);
      advanceAfter(ids, idx);
    } else {
      const idx = openMoves().findIndex(m => m.id === p.move.id);
      await skipMove(p.move.id, choice, opName);
      toast(`Skipped ${p.move.plate}`, choice);
      advanceAfter([p.move.id], idx);
    }
    await refreshModel();
  } catch (e) { toast(`Not recorded: ${e.message}`, null); }
}
function advanceAfter(ids, idx) {
  const rest = openMoves().filter(m => !ids.includes(m.id));
  const next = rest[Math.min(Math.max(0, idx), rest.length - 1)];
  U.detailFor = null;
  if (next) select(next.id, {}); else { U.sel = null; closeDrawer(); syncMap(); }
}
$('#pick').addEventListener('click', e => { const b = e.target.closest('.opt'); if (b) choosePick(+b.dataset.i); });
document.addEventListener('mousedown', e => {
  if (U.pick && !e.target.closest('#pick') && !e.target.closest('[data-assign]') && !e.target.closest('#dAssign') && !e.target.closest('#dSkip')) closePick();
  if (!$('#modelPop').hidden && !e.target.closest('#modelPop') && !e.target.closest('#modelQ')) toggleModel(false);
});

// ---------- model "?" popover ----------
function renderModel() {
  const md = S.model; if (!md) return '';
  const t = md.tabpfn || {}, c = md.carolina || {}, lv = md.live || {}, th = md.threshold || {}, v = md.value || {};
  const lat = lv.latency_p50_s != null ? `median ${lv.latency_p50_s} s per call (last ${lv.last_latency_s} s)` : 'no live call yet';
  const fb = lv.fallback_rate != null ? `${Math.round(lv.fallback_rate * 100)}% of live ride ends fell back to the GBM` : 'no fallback so far';
  return `<h3>How the moves are scored</h3>
    <p><b>Relocate</b>: TabPFN (Prior Labs API) scores every Berlin ride end for the chance the car sits idle more than 12 h. Context: 10k Berlin ride ends from June 3–16 2024, raw features only (hour, weekday, charge, discount, damage count, size, model, electric, position). No training run.</p>
    <p>In June 2024 about 2,700 Berlin cars a day (18% of ride ends) sat idle more than 12 h after a ride.</p>
    <p>On held-out ride ends (June 17–22): AUC <b class="n">${t.auc}</b>, Brier <b class="n">${t.brier}</b>, calibration error <b class="n">${t.ece}</b>. A GBM trained on all 210k June rides reaches AUC ${c.gbm_210k_auc}: TabPFN with 10k rides of context comes within 0.01–0.02 and is better calibrated, so its percentages can be read as odds. Trained on June, it still scores AUC 0.78–0.85 two months later. In a new city with little data it beats the GBM from 50 rides on (Carolina's tests).</p>
    <p><b>Context age</b>: live ride ends are from November 2026, but the context is still June 2024, about 29 months older. Carolina's tests only cover a two-month gap. So trust the ranking (which cars first) and read the exact percentage as approximate. Swapping last week's rides into the context is one API call with no retraining, and halved calibration drift in her tests. It needs a week of labelled rides, and our live scraper only started collecting on 21 Nov 2026, so it isn't wired up yet.</p>
    <p>A car becomes a move at p ≥ ${pct(th.tabpfn)} (top ${Math.round((th.share || 0.1) * 100)}% of ride ends; ${pct(th.precision_tabpfn)} of those really sat >12 h) and only if it nets at least €1 after the move cost: crew ~€${S.snap?.summary?.costs?.crew_eur ?? 20}, else rider credit €${S.snap?.summary?.costs?.rider_eur ?? 5} (both assumed). In our 2024 data, MILES relocations start a median ~25 h after the car's last ride; these are flagged at ride end.</p>
    <p><b>Live</b>: new ride ends are batched every 60 s (every 5 min at night) into one API call; ${lat}; ${fb}${lv.last_error ? ` (last error: ${esc(lv.last_error)})` : ''}. Calls slower than 20 s or failing use the gradient-boosting model instead, and the move says so. Replay uses TabPFN scores computed once, offline (${md.replay_precompute_calls} API calls), out-of-sample.</p>
    <p><b>Money</b>: relocation value = (expected idle here − typical idle at the target at this hour, same vehicle class) × €${(v.eur_per_car_h || 1.364).toFixed(2)} per car-hour, from MILES' 2024 audited report (€227M revenue / ~19k cars / 8,760 h). Every € in the list is net of the move cost (assumed: crew trip ~€${S.snap?.summary?.costs?.crew_eur ?? 20}, rider credit €${S.snap?.summary?.costs?.rider_eur ?? 5}). Ride ends at BER airport are not scored into moves: airport parking is its own business. Clears show exposure: fine €25–55 (BKatV) + MILES admin €29.50, plus the observed tow rate × (Umsetzung up to €225 + €70 admin).</p>
`;
}
function toggleModel(force) {
  const p = $('#modelPop'), q = $('#modelQ');
  const show = force ?? p.hidden;
  if (show) {
    p.innerHTML = renderModel(); p.hidden = false;
    const r = q.getBoundingClientRect();
    p.style.top = r.bottom + 8 + 'px'; p.style.left = Math.max(8, Math.min(innerWidth - p.offsetWidth - 8, r.right - p.offsetWidth)) + 'px';
    if (!reduceMotion.matches) { p.classList.remove('opening'); void p.offsetWidth; p.classList.add('opening'); }
  } else p.hidden = true;
  q.setAttribute('aria-expanded', show);
}
$('#modelQ').addEventListener('click', () => toggleModel());

// ---------- toasts / tooltip ----------
function toast(msg, meta) {
  const t = document.createElement('div'); t.className = 'toast';
  t.innerHTML = `${meta !== null ? '<span class="ok">✓</span>' : ''}<span>${esc(msg)}${meta ? `<br><span class="meta">${esc(meta)}</span>` : ''}</span>`;
  $('#toasts').appendChild(t);
  setTimeout(() => { t.classList.add('out'); setTimeout(() => t.remove(), 220); }, meta === null ? 6000 : 3800);
}
const tip = $('#tip');
let tipEl = null, tipT = 0, tipHideAt = 0;
function showTip(el) {
  if (!el.dataset.def) return;
  tip.textContent = el.dataset.def;
  const r = el.getBoundingClientRect(), tw = tip.offsetWidth, th = tip.offsetHeight;
  let top = r.bottom + 8, up = false;
  if (top + th > innerHeight - 8) { top = r.top - th - 8; up = true; }
  tip.style.left = Math.min(innerWidth - tw - 8, Math.max(8, r.left + r.width / 2 - tw / 2)) + 'px'; tip.style.top = top + 'px';
  tip.classList.toggle('up', up);
  tip.classList.toggle('instant', performance.now() - tipHideAt < 400 || tip.classList.contains('show'));
  tip.classList.add('show');
}
function hideTip() { if (tip.classList.contains('show')) tipHideAt = performance.now(); tip.classList.remove('show'); }
document.addEventListener('mouseover', e => {
  const el = e.target.closest('[data-def]');
  if (el === tipEl) return;
  tipEl = el; clearTimeout(tipT);
  if (!el || !el.dataset.def) return hideTip();
  if (tip.classList.contains('show') || performance.now() - tipHideAt < 400) showTip(el);
  else tipT = setTimeout(() => tipEl === el && showTip(el), 400);
});

// ---------- keyboard (no animation on keyboard actions) ----------
document.addEventListener('keydown', e => {
  const typing = !!e.target.matches?.('input, textarea');
  if (e.key === 'Escape') {
    if (typing) return e.target.blur();
    if (U.pick) return closePick();
    if (!$('#modelPop').hidden) return toggleModel(false);
    if (U.drawer) return closeDrawer();
    return;
  }
  if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
  if (U.pick && /^[1-9]$/.test(e.key)) { e.preventDefault(); return choosePick(+e.key - 1); }
  if (U.pick && e.key === 'Enter') { e.preventDefault(); return choosePick(0); }
  const list = openMoves();
  const i = list.findIndex(m => m.id === U.sel);
  if (e.key === 'j' || e.key === 'ArrowDown') { e.preventDefault(); const n = list[Math.min(list.length - 1, i + 1)]; if (n) select(n.id, {}); }
  else if (e.key === 'k' || e.key === 'ArrowUp') { e.preventDefault(); const n = list[Math.max(0, i - 1)]; if (n) select(n.id, {}); }
  else if (e.key === 'Enter') { e.preventDefault(); const id = U.sel || list[0]?.id; if (id) select(id, { drawer: true }); }
  else if (e.key === 'a') { const r = runOf(U.sel); if (r && runs().includes(r)) { if (r.channel === 'rider') offerRider(findMove(U.sel)); else { U.pickKeyboard = true; openAssign(r); } } }
  else if (e.key === 's') { const m = findMove(U.sel); if (m && isOpen(m.id)) { U.pickKeyboard = true; openSkip(m); } }
  else if (e.key === '?') toggleModel();
  else if (e.key === 'q' || e.key === 'Q') { U.qa = !U.qa; renderQA(); }
});

// ---------- operator + source + speed ----------
const opIn = $('#operator');
opIn.value = opName;
opIn.addEventListener('input', () => { opName = opIn.value.trim() || 'Head of Ops'; try { localStorage.setItem('milesops.operator', opName); } catch {} });
opIn.addEventListener('keydown', e => { if (e.key === 'Enter') opIn.blur(); });
$('#source').addEventListener('click', e => {
  const b = e.target.closest('[data-src]'); if (!b || b.dataset.src === S.source) return;
  U.sel = null; closeDrawer(); U.seen.clear(); M.setMoves([], null); homed = false; relFitted = false;
  connect(b.dataset.src).then(() => fitHome());
});
$('#speed').addEventListener('click', async e => {
  const b = e.target.closest('[data-speed]'); if (!b || b.classList.contains('on')) return;
  try { await setSpeed(+b.dataset.speed); toast(`Replay speed ${b.dataset.speed}×`, 'Shared by everyone watching the replay'); } catch (err) { toast(`Speed not changed: ${err.message}`, null); }
});

// ---------- QA panel (?qa=1 or Q): injects create moves ----------
const QA_KINDS = [['relocate', 'Relocate'], ['clear_active', 'Clear: in restriction'], ['clear_soon', 'Clear: starts soon'], ['clear_far', 'Clear: far from legal']];
$('#qaKinds').innerHTML = QA_KINDS.map(([k, l]) => `<button class="btn sm" data-qa="${k}">${l}</button>`).join('');
function renderQA() {
  $('#qa').hidden = !U.qa; if (!U.qa) return;
  $('#qaWhere').innerHTML = `Adds a fake move to the <b>${S.source}</b> list. Tagged <span class="tag">test</span>, never tallied, gone after 10 min.`;
}
const qaMsg = (t, bad) => { const m = $('#qaMsg'); m.textContent = t; m.classList.toggle('bad', !!bad); };
$('#qa').addEventListener('click', async e => {
  if (e.target.closest('#qaClose')) { U.qa = false; renderQA(); return; }
  if (e.target.closest('#qaClear')) { try { const r = await qaClear(); qaMsg(`Cleared ${r.cleared}`); } catch (err) { qaMsg(err.message, true); } return; }
  const b = e.target.closest('[data-qa]'); if (!b) return;
  b.disabled = true;
  try { const a = await qaInject(b.dataset.qa); qaMsg(`Added test move: ${b.textContent}, ${a.plate || a.vid || ''}`); } catch (err) { qaMsg(err.message, true); }
  finally { setTimeout(() => { b.disabled = false; }, 400); }
});
U.qa = new URLSearchParams(location.search).get('qa') === '1';

// ---------- legend ----------
$('#legend').innerHTML = `<div><i class="lg rel"></i>Relocate</div><div><i class="lg clr"></i>Clear</div><div><i class="lg act"></i>Clock running</div><div><i class="lg car"></i>Parked cars</div>`;

// ---------- arrivals: new moves only ----------
function noteArrivals() {
  const ms = openMoves();
  const settled = S.firstSnapAt && performance.now() - S.firstSnapAt > 1500;
  for (const m of ms) {
    if (U.seen.has(m.id)) continue;
    U.seen.add(m.id);
    if (settled) { U.entered.set(m.id, performance.now()); if (mapReady) setTimeout(() => M.arrive(m), 30); }
  }
}

// ---------- render loop ----------
let mapReady = false, homed = false;
onChange(what => {
  if (what.has('mode') || what.has('all')) renderMode();
  if (what.has('all') || what.has('moves')) {
    noteArrivals();
    if (U.sel && !findMove(U.sel)) { U.sel = null; closeDrawer(); }
    renderHeader(); renderList(); renderTally(); syncMap();
    if (mapReady && homed && !relFitted && !U.sel && relPoints().length) fitHome();
    if (U.drawer && U.sel) renderDrawer();
  }
  if (what.has('all') || what.has('cars')) { if (mapReady) { M.setCars(S.cars); if (!homed && S.cars.size > 50) { homed = true; fitHome(); } } }
  if (what.has('clock')) tickClock();
});
onMapEvent((type, d) => { if (type === 'depart' && mapReady && openMoves().some(m => m.vid === d.vid)) M.ghost(d.lon, d.lat); });
let relFitted = false;
function relPoints() {
  if (S.source !== 'live') return [];
  return openMoves().filter(m => m.kind === 'relocate').flatMap(m => [[m.from.lon, m.from.lat], ...(m.to ? [[m.to.lon, m.to.lat]] : [])]);
}
// Live: frame every open relocation (car + target); otherwise the parked-car extent.
function fitHome() {
  if (!mapReady) return;
  M.fitData([...S.cars.values()].map(([la, lo]) => [lo, la]));
  const pts = relPoints();
  if (pts.length) { relFitted = true; M.fitPoints(pts); }
}
setInterval(tickClock, 1000);
tickClock(); renderQA();
addEventListener('resize', () => M.resize());

(async () => {
  const mapP = M.initMap($('#map'), { pick: id => select(id, { pointer: true, drawer: true }) })
    .then(() => { mapReady = true; M.setCars(S.cars); syncMap(); })
    .catch(e => toast(`The map could not load: ${e.message}`, null));
  await connect(new URLSearchParams(location.search).get('source') === 'replay' ? 'replay' : 'live');
  await mapP;
  fitHome();
})();
window.__ops = { S, U, map: () => M.getMap() };
