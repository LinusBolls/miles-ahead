// Loads the demo fleet (schema: ./types.ts) from our server, falling back to the bundled copy.
import { useEffect, useState } from "react";
import { Platform } from "react-native";
import bundled from "../data/vehicles.json";
import type { FleetDoc, Vehicle } from "./types";

export const BUNDLED = bundled as unknown as FleetDoc;

export const FLEET_URL =
  Platform.OS === "web" && typeof window !== "undefined"
    ? `${window.location.origin}${process.env.EXPO_BASE_URL ?? ""}/api/vehicles.json`
    : "https://miles.bolls.dev/app/api/vehicles.json";

export type FleetState = { doc: FleetDoc; from: "server" | "bundled" };
let cache: FleetState = { doc: BUNDLED, from: "bundled" };
let inflight: Promise<void> | null = null;

/** `from` says which copy is shown ("bundled" = server not reached). Fetched once per app session. */
export function useFleet(): FleetState {
  const [state, setState] = useState(cache);
  useEffect(() => {
    let alive = true;
    if (!inflight) {
      inflight = (async () => {
        try {
          const ctrl = new AbortController();
          const t = setTimeout(() => ctrl.abort(), 6000);
          const r = await fetch(FLEET_URL, { signal: ctrl.signal });
          clearTimeout(t);
          if (!r.ok) throw new Error(String(r.status));
          const doc = (await r.json()) as FleetDoc;
          if (Array.isArray(doc?.vehicles) && doc.vehicles.length) cache = { doc, from: "server" };
        } catch {
          /* keep bundled */
        }
      })();
    }
    inflight.then(() => alive && setState(cache));
    return () => {
      alive = false;
    };
  }, []);
  return state;
}

export const isVan = (v: Vehicle) => v.size === "L" || v.size === "X";
/** Rough range for display only ("~"): petrol ~600 km / EV ~420 km on a full tank. */
export const rangeKm = (v: Vehicle) => Math.round((v.pct / 100) * (v.ev ? 420 : 600));
