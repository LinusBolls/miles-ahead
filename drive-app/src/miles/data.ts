// Vehicle helpers for the MILES-style concept screens. Data = the same demo JSON the Rescue feature serves
// (June 2024 Berlin replay snapshot, see src/rescue/types.ts). Nothing here is live.
import type { Vehicle } from "@/lib/fleet";

export type { Vehicle };
export type LatLon = { lat: number; lon: number };

export const isVan = (v: Vehicle) => v.size === "L" || v.size === "X";
export const rangeKm = (v: Vehicle) => Math.round((v.pct / 100) * (v.ev ? 420 : 600));

/** Model name as shown in the app ("VW Polo GP 2022" -> "VW Polo"). */
export const displayModel = (v: Vehicle) =>
  v.model.replace(/\s+GP\s+\d{4}$/, "").replace(/\s+Automatic$/, "").replace(/\s+Elegance$/, "");

/** Plates in the replay are masked ("B-MI ••10"); keep the mask so no real plate is shown. */
export const displayPlate = (v: Vehicle) => v.plate;

export const fuelLabel = (v: Vehicle) => (v.ev ? "Elektro" : "Benzin");

export const euro = (n: number) => `${n.toFixed(2).replace(".", ",")}€`;
export const euroShort = (n: number) => (Number.isInteger(n) ? `${n}€` : euro(n));

export function metres(a: LatLon, b: LatLon) {
  const k = Math.PI / 180;
  const x = (b.lon - a.lon) * k * Math.cos(((a.lat + b.lat) / 2) * k);
  const y = (b.lat - a.lat) * k;
  return Math.round(Math.sqrt(x * x + y * y) * 6371000);
}
export const distLabel = (m: number) => (m < 1000 ? `${m}m` : `${(m / 1000).toFixed(1).replace(".", ",")}km`);
/** ~80 m/min walking. */
export const walkMin = (m: number) => Math.max(1, Math.round(m / 80));

export type Category = "all" | "S" | "M" | "P" | "van" | "ev";
export const CATEGORIES: { key: Category; label: string }[] = [
  { key: "all", label: "Alle" },
  { key: "S", label: "S" },
  { key: "M", label: "M" },
  { key: "P", label: "Premium" },
  { key: "van", label: "Transporter" },
  { key: "ev", label: "Elektro" },
];
export function inCategory(v: Vehicle, c: Category) {
  if (c === "all") return true;
  if (c === "van") return isVan(v);
  if (c === "ev") return v.ev;
  return v.size === c;
}

/** Simple screen-grid clustering. `cellDeg` = cluster cell size in degrees of longitude. */
export type Cluster = { key: string; lat: number; lon: number; ids: number[] };
export function cluster(vs: Vehicle[], cellDeg: number, keepIds: Set<number>): { singles: Vehicle[]; clusters: Cluster[] } {
  const cells = new Map<string, Vehicle[]>();
  const singles: Vehicle[] = [];
  const latCell = cellDeg * 0.61; // Berlin: 1° lon ≈ 0.61° lat in metres
  for (const v of vs) {
    if (keepIds.has(v.id)) {
      singles.push(v);
      continue;
    }
    const k = `${Math.floor(v.lon / cellDeg)}:${Math.floor(v.lat / latCell)}`;
    const a = cells.get(k);
    if (a) a.push(v);
    else cells.set(k, [v]);
  }
  const clusters: Cluster[] = [];
  for (const [k, a] of cells) {
    if (a.length === 1) singles.push(a[0]);
    else {
      let la = 0, lo = 0;
      for (const v of a) {
        la += v.lat;
        lo += v.lon;
      }
      clusters.push({ key: k, lat: la / a.length, lon: lo / a.length, ids: a.map((v) => v.id) });
    }
  }
  return { singles, clusters };
}
