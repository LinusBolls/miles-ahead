/* Refuel Credit Berlin: nearly empty MILES cars near you that make a ride you're taking anyway cheaper. Vanilla JS, polls api/cars every 15 s. */
/* global maplibregl */
(() => {
  'use strict';
  const API = 'api/';
  const POLL_MS = 15000;
  const PLACES = {
    cic: { lat: 52.49373, lon: 13.44611, name: 'CIC Berlin' },
    alex: { lat: 52.52192, lon: 13.41321, name: 'Alexanderplatz' },
  };
  const BER = { lat: 52.515, lon: 13.40 };
  const WALK_M_PER_MIN = 80, WALK_DETOUR = 1.3;
  const UA = navigator.userAgent;
  const IS_ANDROID = /Android/i.test(UA);
  const IS_IOS = /iPhone|iPad|iPod/i.test(UA) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const APPSTORE = 'https://apps.apple.com/de/app/miles-carsharing-vansharing/id1220185947';
  const PLAY = 'https://play.google.com/store/apps/details?id=com.driveby.app';
  // MILES' universal/app links live on api.app.miles-mobility.com (apple-app-site-association: paths "*").
  const APP_LINK_PATH = 'api.app.miles-mobility.com/mobile/Screen/MapScreen';
  const OPEN_HREF = IS_ANDROID
    ? `intent://${APP_LINK_PATH}#Intent;scheme=https;package=com.driveby.app;S.browser_fallback_url=${encodeURIComponent(PLAY)};end`
    : IS_IOS ? `https://${APP_LINK_PATH}` : APPSTORE;

  const WALK_NEAR = 15, WALK_FAR = 30;   // minutes: default list, and "show farther"
  const PUMP_MIN = 10;                   // our guess at the time a refuel takes at the pump, not measured

  const $ = s => document.querySelector(s);
  const el = {
    live: $('#live'), liveText: $('#liveText'), whereBtn: $('#whereBtn'), whereText: $('#whereText'), whereMenu: $('#whereMenu'),
    best: $('#best'), bestLbl: $('#bestLbl'), bestAmt: $('#bestAmt'), bestCost: $('#bestCost'), bestMeta: $('#bestMeta'), none: $('#none'),
    proof: $('#proof'), list: $('#list'), empty: $('#empty'), ticker: $('#ticker'), evLine: $('#evLine'),
    listTitle: $('#listTitle'), farBtn: $('#farBtn'), mapwrap: $('#mapwrap'),
    tpl: $('#cardTpl'), didLine: $('#didLine'), recenter: $('#recenter'),
  };

  const st = {
    data: null, me: { ...PLACES.cic, src: 'cic' }, far: false, open: null, cards: new Map(),
    shown: [], best: null, polled: 0, fetchErr: null, lastBest: null,
  };

  // ---------- utils ----------
  const hav = (a, b, c, d) => {
    const p = Math.PI / 180, x = Math.sin((c - a) * p / 2) ** 2 + Math.cos(a * p) * Math.cos(c * p) * Math.sin((d - b) * p / 2) ** 2;
    return 12742000 * Math.asin(Math.sqrt(x));
  };
  const eur = (v, d = 2) => (v < 0 ? '−' : '') + '€' + Math.abs(v).toFixed(d).replace(/\.00$/, '');
  const km = m => (m < 950 ? `${Math.round(m / 50) * 50} m` : `${(m / 1000).toFixed(1)} km`);
  const mins = m => Math.max(1, Math.round(m));
  const aMin = m => { const n = mins(m); return `${n === 8 || n === 11 || n === 18 || (n >= 80 && n < 90) ? 'an' : 'a'} ${n}-min`; };
  const ago = s => (s < 60 ? `${Math.max(0, Math.round(s))} s ago` : s < 3600 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`);
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const colorName = c => (c ? c.toLowerCase().replace('grey', 'gray') : '');
  const mapsHref = (lat, lon, mode) => IS_IOS
    ? `https://maps.apple.com/?daddr=${lat},${lon}&dirflg=${mode === 'walk' ? 'w' : 'd'}`
    : `https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}&travelmode=${mode === 'walk' ? 'walking' : 'driving'}`;
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  };
  let token = store.get('drive.token');
  if (!token) { token = Math.random().toString(36).slice(2) + Date.now().toString(36); store.set('drive.token', token); }

  // ---------- what one car saves you, from where you stand ----------
  // net = credit minus unlock and km to the station, i.e. as if the station were a pure detour (the worst case).
  function evaluate(c) {
    const r = st.data.rules;
    const walkM = hav(st.me.lat, st.me.lon, c.lat, c.lon) * WALK_DETOUR;
    const o = { c, walkM, walkMin: walkM / WALK_M_PER_MIN, kind: c.kinds[0] };
    const credit = o.kind === 'ev' ? r.credit_ev : r.credit_fuel;
    const stM = c.st ? c.st.m * r.road_factor : null;
    let driveKm = stM != null ? stM / 1000 : 2;
    if (o.kind === 'ev') driveKm = Math.max(driveKm, c.km_to_threshold || 0, 1.05);  // credit needs > 1 km driven
    else driveKm += 0.3;  // park legally after the pump
    driveKm = Math.round(driveKm * 10) / 10;                         // round first, so the shown sum adds up
    const cost = Math.round((c.unlock + driveKm * c.km_price) * 100) / 100;
    Object.assign(o, { credit, driveKm, cost, net: Math.round((credit - cost) * 100) / 100, stM });
    o.score = o.net - o.walkMin * 0.2;   // a walking minute is worth ~€12/h
    return o;
  }
  const byScore = (a, b) => b.score - a.score;

  // ---------- render ----------
  function render() {
    if (!st.data) return;
    // Only cars that pay credit and save more than they cost. Deals and money-losing cars are never shown.
    const all = st.data.cars.filter(c => c.kinds[0] === 'fuel' || c.kinds[0] === 'ev').map(evaluate).filter(o => o.net > 0);
    const near = all.filter(o => o.walkMin <= WALK_NEAR).sort(byScore);
    const farther = all.filter(o => o.walkMin > WALK_NEAR && o.walkMin <= WALK_FAR).sort(byScore);
    let shown = st.far ? [...near, ...farther].sort(byScore) : near;
    if (st.open) {   // don't reshuffle the list under an open card, and keep it listed even outside the walk limit
      const openO = !shown.some(o => o.c.id === st.open) && all.find(o => o.c.id === st.open);
      if (openO) shown = [openO, ...shown];
      const order = new Map(st.shown.map((o, i) => [o.c.id, i]));
      shown = shown.slice().sort((a, b) => (order.get(a.c.id) ?? 1e9) - (order.get(b.c.id) ?? 1e9));
    }
    st.shown = shown;
    renderBest(near[0] || farther[0] || null, !near.length);
    renderListHead(near.length, farther.length);
    renderList(shown);
    renderTicker();
    renderEv();
    mapUpdate(shown);
    el.empty.hidden = shown.length > 0;
    if (!shown.length) el.empty.textContent = farther.length
      ? `Nothing within a ${WALK_NEAR}-min walk right now. The list refreshes every 15 seconds.`
      : `No nearly empty car within a ${WALK_FAR}-min walk right now. The list refreshes every 15 seconds.`;
  }

  const placeName = () => (st.me.src === 'gps' ? 'you' : esc(st.me.name));

  function renderBest(o, isFar) {
    st.best = o;
    el.best.hidden = !o; el.none.hidden = !!o;
    if (!o) { el.none.innerHTML = `No nearly empty car within a ${WALK_FAR}-min walk of ${placeName()} right now.`; return; }
    el.bestLbl.textContent = isFar ? `Nothing within ${WALK_NEAR} min. Nearest good option` : `Best option near ${st.me.src === 'gps' ? 'you' : st.me.name}`;
    const amt = eur(o.net);
    if (st.lastBest != null && st.lastBest !== amt && !reduce()) {
      el.bestAmt.classList.add('tick'); setTimeout(() => { el.bestAmt.textContent = amt; el.bestAmt.classList.remove('tick'); }, 140);
    } else el.bestAmt.textContent = amt;
    st.lastBest = amt;
    const to = o.c.st ? ` · ${km(o.stM)} to ${esc(stName(o.c.st, o.kind))}` : '';
    el.bestCost.innerHTML = `<b>${mins(o.walkMin)} min walk</b> · ${o.kind === 'ev' ? 'plug in and leave' : `<b>about ${PUMP_MIN} min at the pump</b>`}`;
    el.bestMeta.innerHTML = `${esc(o.c.model)} <span>${esc(o.c.plate)}</span>${to}${o.kind === 'ev' ? ' · charge' : ''}`;
  }

  function renderListHead(nNear, nFar) {
    const n = st.far ? nNear + nFar : nNear, lim = st.far ? WALK_FAR : WALK_NEAR;
    el.listTitle.innerHTML = `${n} car${n === 1 ? '' : 's'} within a ${lim}-min walk<small>Sorted by saving and walk</small>`;
    el.farBtn.hidden = !nFar;
    el.farBtn.textContent = st.far ? `Only ${WALK_NEAR} min` : `Show farther (${nFar})`;
    el.farBtn.setAttribute('aria-pressed', String(st.far));
  }

  function renderEv() {
    const evs = st.data.cars.filter(c => c.kinds[0] === 'ev');
    if (!evs.length) { el.evLine.hidden = true; return; }
    const listed = st.shown.some(o => o.kind === 'ev');
    const nearest = evs.map(c => hav(st.me.lat, st.me.lon, c.lat, c.lon)).sort((a, b) => a - b)[0];
    const minsAway = nearest * WALK_DETOUR / WALK_M_PER_MIN;
    const where = listed ? 'One is in the list above.'
      : `The nearest is ${minsAway <= 45 ? `${aMin(minsAway)} walk` : `${km(nearest)}`} away.`;
    el.evLine.innerHTML = `<b>Electric:</b> charging pays €10, but only ${evs.length} electric MILES in Berlin are low enough right now. ${where}`;
    el.evLine.hidden = false;
  }

  function renderList(shown) {
    const seen = new Set();
    let prev = null;
    for (const o of shown) {
      seen.add(o.c.id);
      let li = st.cards.get(o.c.id);
      const fresh = !li;
      if (fresh) { li = makeCard(o.c.id); st.cards.set(o.c.id, li); }
      fillCard(li, o);
      const want = prev ? prev.nextSibling : el.list.firstChild;
      if (want !== li) el.list.insertBefore(li, want);
      if (fresh && st.polled > 1 && !matchMedia('(prefers-reduced-motion: reduce)').matches)
        li.animate([{ opacity: 0, transform: 'translateY(8px)' }, { opacity: 1, transform: 'none' }], { duration: 320, easing: 'cubic-bezier(0.23,1,0.32,1)' });
      prev = li;
    }
    for (const [id, li] of st.cards) {
      if (seen.has(id)) continue;
      const stillLive = st.data.cars.some(c => c.id === id);
      if (st.open === id && !stillLive) {   // keep the open card, but say it's gone
        li.classList.add('gone');
        li.querySelector('.trip').textContent = 'Just taken or moved. Pick another car.';
        continue;
      }
      li.remove(); st.cards.delete(id);
      if (st.open === id) st.open = null;
    }
  }

  function makeCard(id) {
    const li = el.tpl.content.firstElementChild.cloneNode(true);
    li.dataset.id = id;
    li.querySelector('.row').addEventListener('click', () => toggle(id));
    li.querySelector('.didit').addEventListener('click', e => didIt(id, e.currentTarget));
    return li;
  }

  function fillCard(li, o) {
    const c = o.c, k = o.kind;
    li.className = `card k-${k}${st.open === c.id ? ' sel' : ''}`;
    li.querySelector('.amt').textContent = k === 'ev' ? '€10' : '€5';
    li.querySelector('.what').textContent = k === 'ev' ? 'charge' : 'refuel';
    const isNew = c.since > 0 && (Date.now() / 1000 - c.since) < 180;
    li.querySelector('.title').innerHTML = `${esc(c.model)} <small>${esc(c.plate)}</small>${isNew ? '<span class="new">new</span>' : ''}`;
    li.querySelector('.bar i').style.width = `${Math.max(4, c.pct)}%`;
    li.querySelector('.pct').textContent = c.ev ? `${c.pct}% battery` : `${c.pct}% fuel`;
    li.querySelector('.trip').innerHTML = `<b>${mins(o.walkMin)} min</b> walk, then ${c.st ? `<b>${km(o.stM)}</b> to ${esc(stName(c.st, k))}` : 'find a station'}`;
    li.querySelector('.net b').textContent = eur(o.net);
    li.querySelector('.net small').textContent = 'cheaper';
    if (st.open === c.id) fillDetail(li, o);
  }

  const stName = (s, k) => s.name && !/^(ladestation|charging station|tankstelle)$/i.test(s.name) ? s.name : (s.op || (k === 'ev' ? 'a charger' : 'a fuel station'));

  function fillDetail(li, o) {
    const c = o.c, k = o.kind, s = c.st;
    const walk = `<a href="${mapsHref(c.lat, c.lon, 'walk')}" target="_blank" rel="noopener">${mins(o.walkMin)} min</a>`;
    const id = `${esc(colorName(c.color))} ${esc(c.model)}, plate ends ${esc(c.plate.replace('••', ''))}`;
    let steps;
    if (k === 'ev') {
      const thr = c.km_to_threshold > 0
        ? `<li>Drive at least ${c.km_to_threshold.toFixed(0)} km first<small>It's at ${c.pct}%. The credit needs 30% or less when you plug in.</small></li>` : '';
      steps = `<li>Walk ${walk} to the ${id}</li>
        <li>Book it in the MILES app at the normal km rate<small>Not an hourly or day package.</small></li>${thr}
        <li>Drive about ${km(o.stM)} to ${stationLink(s, k)}<small>${o.stM != null && o.stM < 1050 ? 'The credit needs more than 1 km driven, so take a short loop. ' : ''}${partnerNote(s, k)}</small></li>
        <li>Plug in, start charging in the app, end the rental<small>€10 credit after the ride, valid 90 days, used on your next trip.</small></li>`;
    } else {
      steps = `<li>Walk ${walk} to the ${id}</li>
        <li>Book it in the MILES app at the standard km rate<small>It's at ${c.pct}%; the bonus needs under 25% at the start. Not an hourly or day rate, and not via a partner app.</small></li>
        <li>Drive about ${km(o.stM)} to ${stationLink(s, k)}<small>${partnerNote(s, k)}</small></li>
        <li>In the app, tap “Refueling”, pick the pump, tap “Unlock nozzle” and fill up to 100%<small>Free at partner stations, no payment. About ${PUMP_MIN} min at the pump. MILES says parking minutes while refuelling are compensated with the bonus.</small></li>
        <li>Drive on to where you were going<small>€5 credit after the ride, valid 90 days, used on your next trip. Once per car and rental.</small></li>`;
    }
    li.querySelector('.steps').innerHTML = steps;
    const open = li.querySelector('.open');
    const mobile = IS_IOS || IS_ANDROID;
    open.href = OPEN_HREF;
    open.textContent = mobile ? 'Open MILES' : 'Get the MILES app';
    li.querySelector('.walk').href = mapsHref(c.lat, c.lon, 'walk');
    li.querySelector('.hint').innerHTML = `${mobile ? 'Opens the MILES map, not this car. ' : ''}Find it by plate <b>${esc(c.plate)}</b> in the MILES app.
      <span>No app? <a href="${APPSTORE}" rel="noopener">App Store</a> · <a href="${PLAY}" rel="noopener">Google Play</a></span>`;
    const via = k === 'ev' ? 'the charger' : 'the pump', to = k === 'ev' ? 'to the charger' : 'to the pump and on to a parking spot';
    li.querySelector('.math').textContent = `${eur(o.credit)} credit − ${eur(o.cost)} (${eur(c.unlock)} unlock + ${o.driveKm.toFixed(1)} km × ${eur(c.km_price)} ${to}) = ${eur(o.net)} cheaper, `
      + `if ${via} is a pure detour. If it's on your way, you save closer to ${eur(o.credit, 0)}. Prices are our estimate; the app shows yours.`;
    const b = li.querySelector('.didit');
    if (!b.disabled) b.textContent = 'I did it';
  }

  const stationLink = (s, k) => s ? `<a href="${mapsHref(s.lat, s.lon, 'drive')}" target="_blank" rel="noopener">${esc(stName(s, k))}</a>${s.kw ? ` (${s.kw} kW)` : ''}` : 'the nearest station';
  const partnerNote = (s, k) => !s ? '' : s.partner === 'likely'
    ? (k === 'ev' ? 'Likely a partner charger. Check for a blue pin in the MILES app.' : 'Likely a partner station. Check in the MILES app.')
    : 'Partner status unknown. Check the MILES app before you drive.';

  function renderTicker() {
    const now = Date.now() / 1000;
    const ev = (st.data.events || []).find(e => now - e.t < 900 && e.type === 'new' && st.shown.some(o => o.c.id === e.id));
    if (!ev) { el.ticker.hidden = true; return; }
    const what = `${esc(ev.model)} (${ev.pct}% ${ev.ev ? 'battery' : 'fuel'})`;
    el.ticker.innerHTML = ev.type === 'new'
      ? `<b>${ago(now - ev.t)}:</b> ${what} just showed up${distTxt(ev.id)}.`
      : `<b>${ago(now - ev.t)}:</b> ${what} was just taken or moved.`;
    el.ticker.hidden = false;
  }
  const distTxt = id => { const c = st.data.cars.find(x => x.id === id); return c ? `, ${aMin(hav(st.me.lat, st.me.lon, c.lat, c.lon) * WALK_DETOUR / WALK_M_PER_MIN)} walk away` : ''; };

  function renderLive() {
    const d = st.data;
    el.live.className = 'live';
    if (st.fetchErr && !d) { el.live.classList.add('err'); el.liveText.textContent = 'Offline, retrying'; return; }
    if (!d) return;
    const age = (Date.now() - Date.parse(d.data_at)) / 1000;
    if (st.fetchErr) { el.live.classList.add('err'); el.liveText.textContent = `Connection lost, data ${ago(age)}`; return; }
    if (age > 600) { el.live.classList.add('stale'); el.liveText.textContent = `Data ${ago(age)}`; return; }
    el.live.classList.add('ok');
    el.liveText.textContent = `Live, updated ${ago(age)}`;
  }

  function renderProof() {
    // bridge to the ops view: how many fuel cars on the live MILES map are low right now
    const f = st.data.fleet, low = st.data.cars.filter(c => c.kinds.includes('fuel')).length;
    const fuelCars = f ? f.deployed - f.electric : 0;
    el.proof.hidden = !fuelCars;
    if (fuelCars) el.proof.innerHTML = `<b>${low.toLocaleString('en-US')}</b> of ${fuelCars.toLocaleString('en-US')} MILES fuel cars available in Berlin are under 25% right now <span>(live map data)</span>.`;
    const n = st.data.did_count || 0;
    el.didLine.hidden = !n;
    el.didLine.textContent = `${n} ${n === 1 ? 'person has' : 'people have'} tapped "I did it" here.`;
  }

  // ---------- open / select ----------
  // keepOpen: open (or re-scroll to) the card without closing it if it's already open
  function toggle(id, keepOpen) {
    const was = st.open;
    if (keepOpen && was === id && st.cards.get(id)) { scrollToCard(st.cards.get(id)); return; }
    if (was && st.cards.get(was)) {
      const li = st.cards.get(was);
      li.querySelector('.detail').hidden = true; li.querySelector('.row').setAttribute('aria-expanded', 'false'); li.classList.remove('sel');
    }
    st.open = was === id ? null : id;
    if (st.open) {
      const car = st.data.cars.find(c => c.id === id);
      const o = st.shown.find(x => x.c.id === id) || (car && evaluate(car));
      let li = st.cards.get(id);
      if (!li && o) { // picked outside the list (e.g. best option while "farther" is off): show it on top
        li = makeCard(id); st.cards.set(id, li); el.list.prepend(li); st.shown = [o, ...st.shown];
      }
      if (li && o) {
        fillCard(li, o);
        li.querySelector('.detail').hidden = false; li.querySelector('.row').setAttribute('aria-expanded', 'true');
        scrollToCard(li);
        mapSelect(o);
      }
    } else { mapSelect(null); fitNearest(); }
  }

  // Put the card's header just below the sticky map. scrollIntoView + scroll-margin is unreliable here because the
  // sticky map is only stuck after the hero has scrolled away, and a card closing above shifts the layout.
  function scrollToCard(li) {
    requestAnimationFrame(() => {
      const y = window.scrollY + li.getBoundingClientRect().top - el.mapwrap.offsetHeight - 8;
      window.scrollTo({ top: Math.max(0, y), behavior: reduce() ? 'auto' : 'smooth' });
    });
  }

  async function didIt(id, btn) {
    const c = st.data.cars.find(x => x.id === id);
    if (!c) return;
    btn.disabled = true; btn.textContent = 'Sending';
    try {
      const r = await fetch(API + 'did', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ car: id, kind: c.kinds[0], token }) });
      const j = await r.json();
      btn.textContent = j.ok ? `Thanks. That makes ${j.count}.` : 'Saved already';
    } catch { btn.disabled = false; btn.textContent = 'No connection. Tap again'; }
  }

  // ---------- map ----------
  let map, mapReady = false, meMarker, stMarker;
  const KCOL = { ev: '#0ECAA0', fuel: '#F2A93B' };
  function mapInit() {
    if (!window.maplibregl) { setTimeout(mapInit, 100); return; }
    map = new maplibregl.Map({
      container: 'map', style: 'https://tiles.openfreemap.org/styles/positron', center: [st.me.lon, st.me.lat], zoom: 13.4,
      attributionControl: { compact: true }, fadeDuration: 0, pitchWithRotate: false, dragRotate: false, maxZoom: 18, minZoom: 9,
    });
    map.touchZoomRotate.disableRotation();
    map.on('styleimagemissing', e => { if (!map.hasImage(e.id)) map.addImage(e.id, { width: 1, height: 1, data: new Uint8Array(4) }); });
    map.on('load', () => {
      map.addSource('cars', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      map.addSource('route', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      map.addLayer({ id: 'route', type: 'line', source: 'route', paint: { 'line-color': '#0E1B26', 'line-width': 3, 'line-dasharray': [1.2, 1.4] } });
      map.addLayer({ id: 'credit', type: 'circle', source: 'cars', paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, ['case', ['get', 'sel'], 7, 3.5], 14, ['case', ['get', 'sel'], 13, 10], 17, ['case', ['get', 'sel'], 16, 14]],
        'circle-color': ['match', ['get', 'k'], 'ev', KCOL.ev, KCOL.fuel],
        'circle-stroke-color': ['case', ['get', 'sel'], '#0E1B26', '#fff'], 'circle-stroke-width': ['case', ['get', 'sel'], 3, 2] } });
      map.addLayer({ id: 'credit-lbl', type: 'symbol', source: 'cars', minzoom: 13.5, layout: {
        'text-field': ['get', 'lbl'], 'text-size': 10, 'text-font': ['Noto Sans Bold'], 'text-allow-overlap': true }, paint: { 'text-color': '#0E1B26' } });
      for (const id of ['credit']) {
        map.on('click', id, e => { const f = e.features[0]; if (f) toggle(f.properties.id, true); });
        map.on('mouseenter', id, () => (map.getCanvas().style.cursor = 'pointer'));
        map.on('mouseleave', id, () => (map.getCanvas().style.cursor = ''));
      }
      mapReady = true;
      document.querySelector('.maplibregl-ctrl-attrib')?.classList.remove('maplibregl-compact-show');
      const d = document.createElement('div'); d.className = 'me-dot';
      meMarker = new maplibregl.Marker({ element: d }).setLngLat([st.me.lon, st.me.lat]).addTo(map);
      render(); fitNearest();
    });
  }

  function mapUpdate(all) {
    if (!mapReady) return;
    map.getSource('cars').setData({ type: 'FeatureCollection', features: all.map(o => ({
      type: 'Feature', geometry: { type: 'Point', coordinates: [o.c.lon, o.c.lat] },
      properties: { id: o.c.id, k: o.kind, sel: o.c.id === st.open, lbl: o.kind === 'ev' ? '€10' : '€5' },
    })) });
    meMarker && meMarker.setLngLat([st.me.lon, st.me.lat]);
  }

  function mapSelect(o) {
    if (!mapReady) return;
    stMarker && stMarker.remove(); stMarker = null;
    const feats = [];
    if (o && o.c.st) {
      const s = o.c.st;
      feats.push({ type: 'Feature', geometry: { type: 'LineString', coordinates: [[o.c.lon, o.c.lat], [s.lon, s.lat]] } });
      const d = document.createElement('div');
      d.className = `st-pin ${o.kind}`;
      d.innerHTML = (o.kind === 'ev'
        ? '<svg viewBox="0 0 16 16"><path d="M9.5 1 3 9h4l-1 6 6.5-8h-4z"/></svg>'
        : '<svg viewBox="0 0 16 16"><path d="M3 2h6v12H3zM10 5l2.5 2v5a1 1 0 0 0 2 0V6L12 3.5"/></svg>') + esc(stName(s, o.kind)).slice(0, 22);
      stMarker = new maplibregl.Marker({ element: d, anchor: 'bottom', offset: [0, -4] }).setLngLat([s.lon, s.lat]).addTo(map);
    }
    map.getSource('route').setData({ type: 'FeatureCollection', features: feats });
    mapUpdate(st.shown);
    if (o) {
      const b = new maplibregl.LngLatBounds([st.me.lon, st.me.lat], [st.me.lon, st.me.lat]).extend([o.c.lon, o.c.lat]);
      if (o.c.st) b.extend([o.c.st.lon, o.c.st.lat]);
      map.fitBounds(b, { padding: { top: 46, bottom: 30, left: 36, right: 64 }, maxZoom: 16, duration: reduce() ? 0 : 600 });
    }
  }

  function fitNearest() {
    if (!mapReady || !st.data) return;
    const near = st.shown.length ? st.shown.slice(0, 6) : (st.best ? [st.best] : []);
    const b = new maplibregl.LngLatBounds([st.me.lon, st.me.lat], [st.me.lon, st.me.lat]);
    near.forEach(o => b.extend([o.c.lon, o.c.lat]));
    map.fitBounds(b, { padding: { top: 30, bottom: 30, left: 30, right: 64 }, maxZoom: 15.5, duration: reduce() ? 0 : 500 });
  }
  const reduce = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---------- data ----------
  async function poll() {
    clearTimeout(poll.t);
    try {
      const r = await fetch(API + 'cars', { cache: 'no-cache' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = await r.json();
      if (!j.ok) throw new Error(j.status || 'starting');
      st.fetchErr = null; st.polled++;
      const first = !st.data;
      st.data = j;
      render(); renderProof();
      if (first) fitNearest();
    } catch (e) {
      st.fetchErr = String(e);
    }
    renderLive();
    if (!document.hidden) poll.t = setTimeout(poll, POLL_MS);
  }
  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); else clearTimeout(poll.t); });
  setInterval(renderLive, 1000);

  // ---------- location ----------
  function setMe(p, src, name) {
    st.me = { lat: p.lat, lon: p.lon, src, name };
    el.whereText.textContent = src === 'gps' ? 'Near you' : name;
    for (const b of el.whereMenu.querySelectorAll('button')) b.setAttribute('aria-current', String(b.dataset.where === src));
    st.lastBest = null;
    if (st.open) toggle(st.open);
    render(); fitNearest();
  }
  function locate(explicit) {
    if (!navigator.geolocation) { if (explicit) el.whereText.textContent = 'No location on this device'; return; }
    if (explicit) el.whereText.textContent = 'Locating';
    navigator.geolocation.getCurrentPosition(pos => {
      const p = { lat: pos.coords.latitude, lon: pos.coords.longitude };
      if (hav(p.lat, p.lon, BER.lat, BER.lon) > 40000) { setMe(PLACES.cic, 'cic', 'CIC Berlin'); el.whereText.textContent = 'CIC Berlin (you are outside Berlin)'; return; }
      setMe(p, 'gps', 'you');
    }, () => { if (explicit || st.me.src !== 'cic') setMe(PLACES.cic, 'cic', 'CIC Berlin'); }, { enableHighAccuracy: true, timeout: 9000, maximumAge: 30000 });
  }

  el.whereBtn.addEventListener('click', e => {
    e.stopPropagation();
    const open = el.whereMenu.hidden;
    el.whereMenu.hidden = !open; el.whereBtn.setAttribute('aria-expanded', String(open));
  });
  document.addEventListener('click', () => { el.whereMenu.hidden = true; el.whereBtn.setAttribute('aria-expanded', 'false'); });
  el.whereMenu.addEventListener('click', e => {
    const w = e.target.closest('button')?.dataset.where;
    if (!w) return;
    if (w === 'gps') locate(true); else setMe(PLACES[w], w, PLACES[w].name);
  });
  el.recenter.addEventListener('click', () => { if (st.open) toggle(st.open); fitNearest(); });
  el.farBtn.addEventListener('click', () => { st.far = !st.far; render(); fitNearest(); });
  el.best.addEventListener('click', () => { if (st.best) toggle(st.best.c.id, true); });

  // ?at=lat,lon or ?at=alex|cic for demos
  const at = new URLSearchParams(location.search).get('at');
  if (at && PLACES[at]) setMe(PLACES[at], at, PLACES[at].name);
  else if (at && /^-?\d+(\.\d+)?,-?\d+(\.\d+)?$/.test(at)) { const [la, lo] = at.split(',').map(Number); const near = Object.values(PLACES).find(p => hav(la, lo, p.lat, p.lon) < 400); setMe({ lat: la, lon: lo }, 'pin', near ? near.name : 'this spot'); }
  else locate(false);
  mapInit();
  poll();
})();
