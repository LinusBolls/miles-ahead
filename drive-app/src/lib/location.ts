// The user's location, as a tiny shared store so every screen agrees. GPS when granted, otherwise CIC Berlin. Outside
// Berlin we also fall back to CIC. The last good GPS fix is cached so the background task can check without waking GPS.
import { useSyncExternalStore } from "react";
import * as Location from "expo-location";
import { BERLIN, PLACES } from "./config";
import { haversine } from "./format";
import * as storage from "./storage";
import type { Place } from "./types";

export const CIC: Place = { ...PLACES.cic };

type State = { place: Place; status: "idle" | "locating" };
let state: State = { place: CIC, status: "idle" };
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

function set(next: Partial<State>) {
  state = { ...state, ...next };
  emit();
}

export function cachedLocation(): { lat: number; lon: number } | null {
  const raw = storage.get("lastLoc");
  if (!raw) return null;
  try {
    const { lat, lon } = JSON.parse(raw);
    return typeof lat === "number" && typeof lon === "number" ? { lat, lon } : null;
  } catch {
    return null;
  }
}

function cache(lat: number, lon: number) {
  storage.set("lastLoc", JSON.stringify({ lat, lon, at: Date.now() }));
}

export function setPlace(p: Place) {
  set({ place: p });
}

/** explicit=true asks for permission (a menu tap); false only uses an existing grant and never prompts. */
export async function locate(explicit: boolean) {
  set({ status: "locating" });
  try {
    const perm = explicit
      ? await Location.requestForegroundPermissionsAsync()
      : await Location.getForegroundPermissionsAsync();
    if (!perm.granted) {
      set({ status: "idle", ...(explicit ? { place: { ...CIC } } : {}) });
      return;
    }
    const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
    const lat = pos.coords.latitude;
    const lon = pos.coords.longitude;
    if (haversine(lat, lon, BERLIN.lat, BERLIN.lon) > 40000) {
      set({ status: "idle", place: { ...CIC, name: "CIC Berlin (you're outside Berlin)" } });
    } else {
      cache(lat, lon);
      set({ status: "idle", place: { lat, lon, name: "you", src: "gps" } });
    }
  } catch {
    set({ status: "idle", ...(explicit ? { place: { ...CIC } } : {}) });
  }
}

/**
 * Turn on nearby-rescue alerts: ask foreground location (When-In-Use), cache a fix for the background task, then ask to
 * upgrade to Always so we can check while the app is closed, and register the background check. Safe to call repeatedly.
 */
export async function enableNearbyAlerts(): Promise<boolean> {
  try {
    const fg = await Location.requestForegroundPermissionsAsync();
    if (!fg.granted) return false;
    try {
      const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
      cache(pos.coords.latitude, pos.coords.longitude);
      set({ place: { lat: pos.coords.latitude, lon: pos.coords.longitude, name: "you", src: "gps" } });
    } catch {
      /* keep whatever place we have */
    }
    await Location.requestBackgroundPermissionsAsync(); // Always; OK if the user declines, foreground checks still run
    const { registerBackgroundCheck } = await import("./background");
    await registerBackgroundCheck();
    return true;
  } catch {
    return false;
  }
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}
const getState = () => state;

export function useLocationStore(): State & { setPlace: typeof setPlace; locate: typeof locate } {
  const s = useSyncExternalStore(subscribe, getState, getState);
  return { ...s, setPlace, locate };
}
