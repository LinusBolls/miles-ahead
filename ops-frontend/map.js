// Map: muted OpenFreeMap dark basemap. Shows only the move cars, the selected run's route (car -> target legs, dashed
// links the agent rides between moves, numbered stops) and, as faint context, every parked car. No paid-zone choropleth.
/* global maplibregl */

const C = { ground: '#0D1222', brand: '#0ECAA0', signal: '#F59E3B', clear: '#C9D2DF', faint: '#5E6B80', ink: '#EEF2F7' };
const STYLE = 'https://tiles.openfreemap.org/styles/dark';
const FALLBACK_STYLE = 'https://tiles.openfreemap.org/styles/positron';
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)');
let map, ready = false, onPick = () => {};
const empty = () => ({ type: 'FeatureCollection', features: [] });

export function initMap(el, { pick }) {
  onPick = pick;
  map = new maplibregl.Map({ container: el, style: STYLE, center: [13.395, 52.515], zoom: 11.2, minZoom: 8, maxZoom: 18,
    attributionControl: { compact: true }, fadeDuration: 0, pitchWithRotate: false, dragRotate: false });
  map.touchZoomRotate.disableRotation();
  map.on('styleimagemissing', e => { if (!map.hasImage(e.id)) map.addImage(e.id, { width: 1, height: 1, data: new Uint8Array(4) }); });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
  map.on('error', e => {
    if (!ready && e?.error && /style/.test(String(e.error.message || '')) && !map.__fallback) { map.__fallback = true; map.setStyle(FALLBACK_STYLE); }
  });
  return new Promise(res => map.on('load', () => { muteBasemap(); initLayers(); ready = true; res(map); }));
}

function muteBasemap() {
  for (const l of map.getStyle().layers) {
    const id = l.id;
    try {
      if (l.type === 'background') map.setPaintProperty(id, 'background-color', C.ground);
      else if (l.type === 'fill') {
        if (/water/.test(id)) map.setPaintProperty(id, 'fill-color', '#0A1426');
        else if (/building/.test(id)) { map.setPaintProperty(id, 'fill-color', '#131A2B'); map.setPaintProperty(id, 'fill-opacity', 0.9); }
        else map.setPaintProperty(id, 'fill-color', '#10172A');
        if (l.paint?.['fill-pattern']) map.setPaintProperty(id, 'fill-pattern', undefined);
      } else if (l.type === 'line') {
        const major = /motorway|major|trunk|primary/.test(id);
        map.setPaintProperty(id, 'line-color', /water/.test(id) ? '#0A1426' : /rail/.test(id) ? '#1A2132' : /boundary/.test(id) ? '#2A3446' : major ? '#1F2839' : '#171E2F');
        if (/rail|path|pier/.test(id)) map.setPaintProperty(id, 'line-opacity', 0.5);
      } else if (l.type === 'symbol') {
        const big = /place_city|place_town|place_suburb/.test(id);
        map.setPaintProperty(id, 'text-color', big ? '#6B788D' : '#4A566B');
        map.setPaintProperty(id, 'text-halo-color', C.ground);
        if (/road_oneway|poi/.test(id)) map.setLayoutProperty(id, 'visibility', 'none');
      }
    } catch {}
  }
}

const K = ['coalesce', ['feature-state', 'k'], 1];   // entrance scale 0.6 -> 1
const O = ['coalesce', ['feature-state', 'o'], 1];   // entrance opacity 0 -> 1
const colorOf = ['case', ['get', 'act'], C.signal, ['==', ['get', 'kind'], 'relocate'], C.brand, C.clear];

function initLayers() {
  map.addSource('cars', { type: 'geojson', data: empty() });
  map.addLayer({ id: 'cars', type: 'circle', source: 'cars', paint: {
    'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, 0.9, 13, 1.6, 16, 3],
    'circle-color': '#7D8AA0', 'circle-opacity': ['interpolate', ['linear'], ['zoom'], 10, 0.16, 14, 0.28] } });
  map.addSource('route', { type: 'geojson', data: empty() });
  map.addLayer({ id: 'route-link', type: 'line', source: 'route', filter: ['==', ['get', 't'], 'link'],
    layout: { 'line-cap': 'round' }, paint: { 'line-color': C.ink, 'line-opacity': 0.35, 'line-width': 1.2, 'line-dasharray': [1.5, 2] } });
  map.addLayer({ id: 'route-leg', type: 'line', source: 'route', filter: ['==', ['get', 't'], 'leg'],
    layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': colorOf, 'line-width': ['interpolate', ['linear'], ['zoom'], 11, 2, 15, 3.5], 'line-opacity': 0.9 } });
  map.addLayer({ id: 'route-to', type: 'circle', source: 'route', filter: ['==', ['get', 't'], 'to'], paint: {
    'circle-radius': ['interpolate', ['linear'], ['zoom'], 11, 3.5, 15, 6], 'circle-color': C.ground,
    'circle-stroke-color': colorOf, 'circle-stroke-width': 2 } });
  map.addSource('moves', { type: 'geojson', data: empty(), promoteId: 'id' });
  map.addLayer({ id: 'moves', type: 'circle', source: 'moves', layout: { 'circle-sort-key': ['case', ['get', 'sel'], 3, ['get', 'act'], 2, 1] }, paint: {
    'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, ['*', K, ['case', ['get', 'sel'], 5.5, 3.6]], 15, ['*', K, ['case', ['get', 'sel'], 9, 6.5]]],
    'circle-color': colorOf, 'circle-opacity': ['*', O, ['case', ['get', 'dim'], 0.35, 1]],
    'circle-stroke-color': C.ground, 'circle-stroke-width': 1.5, 'circle-stroke-opacity': O } });
  map.addLayer({ id: 'moves-num', type: 'symbol', source: 'moves', filter: ['>', ['get', 'n'], 0], layout: {
    'text-field': ['to-string', ['get', 'n']], 'text-font': ['Noto Sans Bold'], 'text-size': 11, 'text-offset': [0, -1.35], 'text-allow-overlap': true },
    paint: { 'text-color': C.ink, 'text-halo-color': C.ground, 'text-halo-width': 1.6 } });
  map.on('mouseenter', 'moves', () => (map.getCanvas().style.cursor = 'pointer'));
  map.on('mouseleave', 'moves', () => (map.getCanvas().style.cursor = ''));
  map.on('click', e => {
    const f = map.queryRenderedFeatures([[e.point.x - 5, e.point.y - 5], [e.point.x + 5, e.point.y + 5]], { layers: ['moves'] })[0];
    if (f) onPick(f.properties.id);
  });
}

let carsT = 0, carsPending = null;
export function setCars(cars) {
  carsPending = cars;
  if (carsT) return;
  carsT = setTimeout(() => {
    carsT = 0;
    if (!ready || !carsPending) return;
    const feats = [];
    for (const [, [lat, lon]] of carsPending) feats.push({ type: 'Feature', geometry: { type: 'Point', coordinates: [lon, lat] }, properties: {} });
    map.getSource('cars').setData({ type: 'FeatureCollection', features: feats });
  }, 500);
}

let lastKey = '';
// moves: [{m, run, n (stop number in selected run or 0), sel, dim}]
export function setMoves(items, run) {
  if (!ready) return;
  const feats = items.map(({ m, n, sel, dim }) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [m.from.lon, m.from.lat] },
    properties: { id: m.id, kind: m.kind, act: !!m.act_now, n: n || 0, sel: !!sel, dim: !!dim } }));
  const key = feats.map(f => `${f.properties.id}${f.properties.n}${f.properties.sel ? 's' : ''}${f.properties.dim ? 'd' : ''}`).join() + '|' + (run?.id || '') + (run?.moves?.length || 0);
  if (key === lastKey) return;
  lastKey = key;
  map.getSource('moves').setData({ type: 'FeatureCollection', features: feats });
  const r = [];
  if (run) {
    let prev = null;
    for (const m of run.moves) {
      const to = m.to || m.from;
      const props = { kind: m.kind, act: !!m.act_now };
      if (prev) r.push({ type: 'Feature', geometry: { type: 'LineString', coordinates: [[prev.lon, prev.lat], [m.from.lon, m.from.lat]] }, properties: { t: 'link', ...props } });
      if (m.to) {
        r.push({ type: 'Feature', geometry: { type: 'LineString', coordinates: [[m.from.lon, m.from.lat], [to.lon, to.lat]] }, properties: { t: 'leg', ...props } });
        r.push({ type: 'Feature', geometry: { type: 'Point', coordinates: [to.lon, to.lat] }, properties: { t: 'to', ...props } });
      }
      prev = to;
    }
  }
  map.getSource('route').setData({ type: 'FeatureCollection', features: r });
}

// camera: fit a run (pointer = animated, keyboard = instant)
let inset = 0; // px of map hidden behind the detail drawer (left edge)
export function setInset(px) { inset = px; }
export function fitRun(run, animate) {
  if (!ready || !run) return;
  const b = new maplibregl.LngLatBounds();
  for (const m of run.moves) { b.extend([m.from.lon, m.from.lat]); if (m.to) b.extend([m.to.lon, m.to.lat]); }
  map.fitBounds(b, { padding: { top: 80, bottom: 80, left: 80 + inset, right: 80 }, maxZoom: 15, duration: animate && !reduceMotion.matches ? 600 : 0 });
}
export function panTo(m, animate) {
  if (!ready || !m) return;
  const b = map.getBounds();
  if (b.contains([m.from.lon, m.from.lat]) && (!m.to || b.contains([m.to.lon, m.to.lat]))) return;
  map.easeTo({ center: [m.from.lon, m.from.lat], duration: animate && !reduceMotion.matches ? 500 : 0 });
}

// ---------- arrivals: only for new moves ----------
let fxLive = 0;
function fx(lon, lat, cls, ms) {
  if (!ready || fxLive >= 24 || document.hidden || !map.getBounds().contains([lon, lat])) return;
  const el = document.createElement('div');
  el.className = 'fx';
  el.innerHTML = cls.map(c => `<i class="${c}"></i>`).join('');
  const mk = new maplibregl.Marker({ element: el }).setLngLat([lon, lat]).addTo(map);
  fxLive++;
  setTimeout(() => { mk.remove(); fxLive--; }, ms);
}
export function arrive(m) {
  if (m.act_now) fx(m.from.lon, m.from.lat, ['rip act', 'rip act r2', 'core act'], 1500);
  else fx(m.from.lon, m.from.lat, ['rip'], 900);
  enter(m.id);
}
export function ghost(lon, lat) { fx(lon, lat, ['gh'], 450); }

const entering = new Map();
let raf = 0;
const easeOut = t => 1 - Math.pow(1 - t, 4);
function enter(id) {
  entering.set(id, performance.now());
  try { map.setFeatureState({ source: 'moves', id }, { k: reduceMotion.matches ? 1 : 0.6, o: 0 }); } catch {}
  if (!raf) raf = requestAnimationFrame(step);
}
function step(now) {
  for (const [id, t0] of entering) {
    const t = Math.min(1, (now - t0) / 220), e = easeOut(t);
    try { map.setFeatureState({ source: 'moves', id }, { k: reduceMotion.matches ? 1 : 0.6 + 0.4 * e, o: e }); } catch {}
    if (t >= 1) entering.delete(id);
  }
  raf = entering.size ? requestAnimationFrame(step) : 0;
}

let homeB = null;
export function fitData(points) {
  if (!ready) return;
  const pts = points.filter(([lon, lat]) => lat > 52.3 && lat < 52.7 && lon > 13.05 && lon < 13.8);
  if (pts.length < 5) return;
  const q = (a, p) => a[Math.min(a.length - 1, Math.max(0, Math.floor(p * (a.length - 1))))];
  const xs = pts.map(p => p[0]).sort((a, b) => a - b), ys = pts.map(p => p[1]).sort((a, b) => a - b);
  homeB = [[q(xs, 0.03), q(ys, 0.03)], [q(xs, 0.97), q(ys, 0.97)]];
  home(false);
}
export function home(animate = true) {
  if (!ready) return;
  if (homeB) map.fitBounds(homeB, { padding: 50, maxZoom: 12.4, duration: animate && !reduceMotion.matches ? 600 : 0 });
}
export function resize() { if (ready) map.resize(); }
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export function getMap() { return map; }
