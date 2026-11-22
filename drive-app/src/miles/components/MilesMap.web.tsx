// Web MILES-style map: self-hosted MapLibre (same loader approach as components/FleetMap.web.tsx, no npm dep),
// OpenFreeMap "positron" restyled toward the app's light-grey/green look, CARTO light raster as a fallback.
// Pins and cluster discs are drawn on canvas (our own drawings) and rendered as symbol layers.
import { useEffect, useRef } from "react";
import type { MilesMapProps } from "./mapTypes";

declare global {
  interface Window {
    maplibregl?: any;
  }
}

const BASE = process.env.EXPO_BASE_URL ?? "";
const STYLE_URL = "https://tiles.openfreemap.org/styles/positron";
const RASTER_FALLBACK = {
  version: 8,
  sources: {
    carto: {
      type: "raster",
      tiles: ["https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png"],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors © CARTO",
    },
  },
  layers: [{ id: "carto", type: "raster", source: "carto" }],
};

let loader: Promise<any> | null = null;
function loadMapLibre(): Promise<any> {
  if (window.maplibregl) return Promise.resolve(window.maplibregl);
  if (loader) return loader;
  loader = new Promise((resolve, reject) => {
    if (!document.querySelector('link[href$="maplibre-gl.css"]')) {
      const css = document.createElement("link");
      css.rel = "stylesheet";
      css.href = `${BASE}/vendor/maplibre-gl.css`;
      document.head.appendChild(css);
    }
    const s = document.createElement("script");
    s.src = `${BASE}/vendor/maplibre-gl.js`;
    s.onload = () => resolve(window.maplibregl);
    s.onerror = reject;
    document.head.appendChild(s);
  });
  return loader;
}

const DPR = 2;
const FONT = `-apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif`;
function canvas(w: number, h: number) {
  const c = document.createElement("canvas");
  c.width = w * DPR;
  c.height = h * DPR;
  const g = c.getContext("2d")!;
  g.scale(DPR, DPR);
  return { c, g };
}
const asImage = (c: HTMLCanvasElement) => ({
  width: c.width,
  height: c.height,
  data: new Uint8Array(c.getContext("2d")!.getImageData(0, 0, c.width, c.height).data.buffer),
});

function carPin(scale: number) {
  const r = 15 * scale, w = r * 2 + 4, h = r * 2 + 13 * scale;
  const { c, g } = canvas(w, h);
  const cx = w / 2, cy = r + 2;
  g.fillStyle = "#000";
  g.beginPath();
  g.moveTo(cx - 5 * scale, cy + r - 4);
  g.lineTo(cx, h - 1);
  g.lineTo(cx + 5 * scale, cy + r - 4);
  g.fill();
  g.beginPath();
  g.arc(cx, cy, r, 0, Math.PI * 2);
  g.fill();
  g.lineWidth = 1.5;
  g.strokeStyle = "#fff";
  g.stroke();
  g.fillStyle = "#fff";
  g.font = `italic 900 ${15 * scale}px ${FONT}`;
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.fillText("M", cx, cy + 0.5);
  return asImage(c);
}

function clusterDisc(n: number) {
  const d = n >= 100 ? 46 : n >= 10 ? 40 : 34;
  const { c, g } = canvas(d, d);
  g.fillStyle = "#000";
  g.beginPath();
  g.arc(d / 2, d / 2, d / 2, 0, Math.PI * 2);
  g.fill();
  g.fillStyle = "#fff";
  g.font = `700 15px ${FONT}`;
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.fillText(String(n), d / 2, d / 2 + 0.5);
  return asImage(c);
}

/** Pull positron toward the app's look: grey ground, white roads, green parks, soft blue water. */
function restyle(m: any) {
  const layers: any[] = m.getStyle()?.layers ?? [];
  for (const l of layers) {
    const id: string = l.id;
    try {
      if (l.type === "background") m.setPaintProperty(id, "background-color", "#eceef2");
      else if (l.type === "fill" && /park|wood|grass|landcover|landuse_park|nature/.test(id))
        m.setPaintProperty(id, "fill-color", "#c9e7b6");
      else if (l.type === "fill" && /water/.test(id)) m.setPaintProperty(id, "fill-color", "#c3d8ee");
      else if (l.type === "fill" && /building/.test(id)) m.setPaintProperty(id, "fill-color", "#e3e5ea");
      else if (l.type === "line" && /highway|road|street|tunnel|bridge/.test(id) && !/casing/.test(id))
        m.setPaintProperty(id, "line-color", "#ffffff");
      else if (l.type === "symbol" && /poi/.test(id)) m.setLayoutProperty(id, "visibility", "none");
      else if (l.type === "symbol") m.setPaintProperty(id, "text-color", "#7d8291");
    } catch {
      /* layer without that property */
    }
  }
}

function el(html: string) {
  const d = document.createElement("div");
  d.innerHTML = html;
  return d.firstElementChild as HTMLElement;
}

export function MilesMap(p: MilesMapProps) {
  const host = useRef<HTMLDivElement>(null);
  const map = useRef<any>(null);
  const ready = useRef(false);
  const overlays = useRef<Map<number, any>>(new Map());
  const meMarker = useRef<any>(null);
  const destMarker = useRef<any>(null);
  const latest = useRef(p);
  latest.current = p;

  useEffect(() => {
    let cancelled = false;
    loadMapLibre().then((ml) => {
      if (cancelled || !host.current) return;
      let fellBack = false;
      const mp = new ml.Map({
        container: host.current,
        style: STYLE_URL,
        center: [p.center.lon, p.center.lat],
        zoom: 15.2,
        attributionControl: false,
        dragRotate: false,
        pitchWithRotate: false,
        touchPitch: false,
      });
      mp.touchZoomRotate.disableRotation();
      // bottom-left: the shared index.html moves bottom-right controls to the top for the Rescue screen
      mp.addControl(new ml.AttributionControl({ compact: true }), "bottom-left");
      map.current = mp;
      (window as any).__milesMap = mp; // QA hook
      mp.on("error", (e: any) => {
        if (!ready.current && !fellBack && String(e?.error?.message || "").length) {
          fellBack = true;
          mp.setStyle(RASTER_FALLBACK);
        }
      });
      mp.on("styleimagemissing", (e: any) => {
        const id: string = e.id;
        if (id.startsWith("cl-") && !mp.hasImage(id)) mp.addImage(id, clusterDisc(Number(id.slice(3))), { pixelRatio: DPR });
      });
      const setup = () => {
        if (mp.getSource("cars")) return;
        if (!fellBack) restyle(mp);
        mp.addImage("m-pin", carPin(1), { pixelRatio: DPR });
        mp.addImage("m-pin-sel", carPin(1.3), { pixelRatio: DPR });
        mp.addSource("route", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        mp.addLayer({
          id: "route",
          type: "line",
          source: "route",
          layout: { "line-cap": "round", "line-join": "round" },
          paint: { "line-color": "#000", "line-width": 3.5, "line-dasharray": [0.6, 2] },
        });
        mp.addSource("cars", {
          type: "geojson",
          data: { type: "FeatureCollection", features: [] },
          cluster: true,
          clusterRadius: 44,
          clusterMaxZoom: 15,
        });
        mp.addSource("loose", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        mp.addLayer({
          id: "clusters",
          type: "symbol",
          source: "cars",
          filter: ["has", "point_count"],
          layout: {
            "icon-image": ["concat", "cl-", ["to-string", ["get", "point_count"]]],
            "icon-allow-overlap": true,
            "icon-ignore-placement": true,
          },
        });
        const pinLayout = {
          "icon-image": ["get", "img"],
          "icon-anchor": "bottom",
          "icon-allow-overlap": true,
          "icon-ignore-placement": true,
          "symbol-sort-key": ["get", "z"],
        };
        mp.addLayer({ id: "cars", type: "symbol", source: "cars", filter: ["!", ["has", "point_count"]], layout: pinLayout });
        mp.addLayer({ id: "loose", type: "symbol", source: "loose", layout: pinLayout });
        const pick = (e: any) => {
          const f = e.features?.[0];
          if (!f) return;
          (e.originalEvent as any).__pin = true;
          latest.current.onSelectVehicle(Number(f.properties.id));
        };
        mp.on("click", "cars", pick);
        mp.on("click", "loose", pick);
        mp.on("click", "clusters", (e: any) => {
          const f = e.features?.[0];
          if (!f) return;
          (e.originalEvent as any).__pin = true;
          mp.easeTo({ center: f.geometry.coordinates, zoom: mp.getZoom() + 1.6, duration: 350 });
        });
        mp.on("click", (e: any) => {
          if (!(e.originalEvent as any).__pin) latest.current.onMapPress?.();
        });
        for (const l of ["cars", "loose", "clusters"]) {
          mp.on("mouseenter", l, () => (mp.getCanvas().style.cursor = "pointer"));
          mp.on("mouseleave", l, () => (mp.getCanvas().style.cursor = ""));
        }
        ready.current = true;
        sync();
        applyFocus(false);
        // keep attribution as the small (i) button so it doesn't cover the top controls
        host.current?.querySelector(".maplibregl-ctrl-attrib")?.classList.remove("maplibregl-compact-show");
      };
      mp.on("load", setup);
      mp.on("styledata", () => {
        if (fellBack && mp.isStyleLoaded()) setup();
      });
    });
    return () => {
      cancelled = true;
      for (const mk of overlays.current.values()) mk.remove();
      overlays.current.clear();
      map.current?.remove();
      map.current = null;
      ready.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function sync() {
    const mp = map.current, ml = window.maplibregl;
    if (!mp || !ready.current || !ml) return;
    const q = latest.current;
    const keep = new Set<number>(q.overlayIds ?? []);
    if (q.selectedId != null) keep.add(q.selectedId);
    const feat = (v: (typeof q.vehicles)[number]) => {
      const sel = v.id === q.selectedId;
      return {
        type: "Feature",
        geometry: { type: "Point", coordinates: [v.lon, v.lat] },
        properties: { id: v.id, img: sel ? "m-pin-sel" : "m-pin", z: sel ? 3 : keep.has(v.id) ? 2 : 1 },
      };
    };
    mp.getSource("cars")?.setData({ type: "FeatureCollection", features: q.vehicles.filter((v) => !keep.has(v.id)).map(feat) });
    mp.getSource("loose")?.setData({ type: "FeatureCollection", features: q.vehicles.filter((v) => keep.has(v.id)).map(feat) });

    // overlay slot (DOM markers above the pin), e.g. Rescue's €5 badge
    const want = new Map<number, string>();
    if (q.webOverlayHtml || q.renderMarkerOverlay) {
      for (const v of q.vehicles) {
        if (!keep.has(v.id)) continue;
        let html = q.webOverlayHtml?.(v) ?? null;
        if (html == null && q.renderMarkerOverlay) {
          const node = q.renderMarkerOverlay(v);
          if (typeof node === "string" || typeof node === "number")
            html = `<div style="background:#2a8cf0;color:#fff;font:800 12px ${FONT};padding:3px 7px;border-radius:999px;border:1.5px solid #fff;white-space:nowrap">${String(node).replace(/[<>&]/g, "")}</div>`;
        }
        if (html) want.set(v.id, html);
      }
    }
    for (const [id, mk] of overlays.current) {
      if (!want.has(id)) {
        mk.remove();
        overlays.current.delete(id);
      }
    }
    for (const [id, html] of want) {
      const v = q.vehicles.find((x) => x.id === id)!;
      const sel = id === q.selectedId;
      overlays.current.get(id)?.remove();
      const node = el(`<div style="pointer-events:none">${html}</div>`);
      overlays.current.set(
        id,
        new ml.Marker({ element: node, anchor: "bottom", offset: [0, sel ? -50 : -40] }).setLngLat([v.lon, v.lat]).addTo(mp),
      );
    }

    mp.getSource("route")?.setData({
      type: "FeatureCollection",
      features:
        q.route && q.route.length > 1
          ? [{ type: "Feature", geometry: { type: "LineString", coordinates: q.route.map((c) => [c.lon, c.lat]) }, properties: {} }]
          : [],
    });
    destMarker.current?.remove();
    destMarker.current = null;
    if (q.dest) {
      const name = q.dest.name.replace(/[<>&]/g, "");
      destMarker.current = new ml.Marker({
        anchor: "bottom",
        element: el(
          `<div style="display:flex;flex-direction:column;align-items:center;pointer-events:none"><div style="background:#000;color:#fff;font:700 12px ${FONT};padding:4px 8px;border-radius:8px;margin-bottom:4px;white-space:nowrap">${name}</div><div style="width:24px;height:24px;border-radius:12px;border:3px solid #2979ff;background:rgba(41,121,255,.15);box-sizing:border-box;display:flex;align-items:center;justify-content:center"><div style="width:8px;height:8px;border-radius:4px;background:#2979ff"></div></div></div>`,
        ),
      })
        .setLngLat([q.dest.lon, q.dest.lat])
        .addTo(mp);
    }

    if (q.me) {
      if (!meMarker.current)
        meMarker.current = new ml.Marker({
          element: el(
            `<div style="width:24px;height:24px;border-radius:12px;background:rgba(41,121,255,.18);display:flex;align-items:center;justify-content:center"><div style="width:14px;height:14px;border-radius:7px;background:#2979ff;border:2.5px solid #fff;box-sizing:border-box"></div></div>`,
          ),
        })
          .setLngLat([q.me.lon, q.me.lat])
          .addTo(mp);
      else meMarker.current.setLngLat([q.me.lon, q.me.lat]);
    }
  }

  useEffect(sync, [p.vehicles, p.selectedId, p.overlayIds, p.me, p.renderMarkerOverlay, p.webOverlayHtml, p.route, p.dest]);

  function applyFocus(animate = true) {
    const mp = map.current, q = latest.current;
    if (!mp || !ready.current || !q.focus || !q.focus.length) return;
    const pad = { top: (q.topInset ?? 80) + 30, bottom: (q.bottomInset ?? 0) + 30, left: 40, right: 40 };
    if (q.focus.length === 1) {
      mp.easeTo({ center: [q.focus[0].lon, q.focus[0].lat], zoom: Math.max(mp.getZoom(), 15.4), padding: pad, duration: animate ? 500 : 0 });
      return;
    }
    let w = 180, e = -180, s = 90, n = -90;
    for (const c of q.focus) {
      w = Math.min(w, c.lon); e = Math.max(e, c.lon); s = Math.min(s, c.lat); n = Math.max(n, c.lat);
    }
    mp.fitBounds([[w, s], [e, n]], { padding: pad, maxZoom: 16.2, duration: animate ? 600 : 0 });
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => applyFocus(true), [p.focusKey]);

  useEffect(() => {
    const mp = map.current;
    if (!mp || p.recenterKey === undefined) return;
    mp.easeTo({ center: [p.center.lon, p.center.lat], zoom: 15, duration: 400 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.recenterKey]);

  useEffect(() => {
    const mp = map.current;
    const v = p.vehicles.find((x) => x.id === p.selectedId);
    if (!mp || !v || p.focus) return; // with `focus`, the host drives the camera
    mp.easeTo({
      center: [v.lon, v.lat],
      zoom: Math.max(mp.getZoom(), 15.6),
      padding: { top: 0, bottom: p.bottomInset ?? 0, left: 0, right: 0 },
      duration: 400,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.selectedId]);

  return <div ref={host} style={{ position: "absolute", inset: 0, background: "#eceef2" }} />;
}
