// Rescue offers: which cars get a €5 badge for a user at a given point, and the offer copy.
// The TabPFN flag and the value-map destination are precomputed in the fleet snapshot (see ./types.ts); here we only
// add the walk from where the user is.
import { haversine } from "@/lib/format";
import { WALK_DETOUR, WALK_M_PER_MIN } from "@/lib/config";
import type { LatLon, ScoredRescue, Vehicle } from "./types";

export const REWARD_EUR = 5;
/** Offers are only made within this walk: the money-back promise is priced for short walks. */
export const RESCUE_WALK_MAX = 15;
/** "97% still there": the policy only offers cars predicted >= 95% still there on arrival (MISSION, Model 2).
 *  The per-car Model 2 score is not wired into this demo, so the policy figure is shown. */
export const STILL_THERE = 0.97;
/** Mean TabPFN P(idle > 12 h) over all 266k replay ride ends (0.168): the "typical car" reference. */
export const TYPICAL_P = 17;
/** How long a rescue reservation holds the car. */
export const HOLD_MIN = 15;
/** Straight line -> street distance when driving; ~25 km/h city average. */
export const ROAD_FACTOR = 1.35;
export const driveMinutes = (m: number) => Math.max(2, Math.round((m * ROAD_FACTOR) / 420));

export function walkFrom(me: LatLon, v: LatLon) {
  const walkM = haversine(me.lat, me.lon, v.lat, v.lon) * WALK_DETOUR;
  return { walkM, walkMin: walkM / WALK_M_PER_MIN };
}

export function scoreRescue(v: Vehicle, me: LatLon): ScoredRescue {
  const { walkM, walkMin } = walkFrom(me, v);
  const p = v.rescue?.p ?? 0;
  return {
    ...v,
    rescue: v.rescue!,
    credit: REWARD_EUR,
    walkM,
    walkMin,
    stillThere: STILL_THERE,
    score: p * 10 - walkMin * 0.2, // riskier first, minus the walk
  };
}

/** Rescue cars (with a destination) within RESCUE_WALK_MAX of `me`, best first. */
export function rankRescues(cars: Vehicle[], me: LatLon): ScoredRescue[] {
  return cars
    .filter((v) => v.rescue?.dest)
    .map((v) => scoreRescue(v, me))
    .filter((c) => c.walkMin <= RESCUE_WALK_MAX)
    .sort((a, b) => b.score - a.score);
}

export const stillPct = (p: number) => Math.round(p * 100);

/** "€5 · 4 min walk · 97% still there · money back if gone" — the offer, verbatim format. */
export function offerLine(o: { credit: number; walkMin: number; stillThere: number }): string {
  return `€${o.credit} · ${Math.max(1, Math.round(o.walkMin))} min walk · ${stillPct(o.stillThere)}% still there · money back if gone`;
}

export const hours = (h: number) =>
  h < 1 ? `${Math.max(10, Math.round((h * 60) / 10) * 10)} min` : `${Math.round(h)} h`;
