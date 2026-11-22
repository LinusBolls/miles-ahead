// The Rescue flow as one hook, so any host map (the temporary one in src/app/index.tsx, or the MILES replica in
// src/miles/) can drive it: offers near the user, reserve -> walk -> drive -> credit, and the engagement calls
// (Live Activity on stage changes, widget data whenever the nearby list changes).
import { useCallback, useEffect, useMemo, useState } from "react";
import { haptic } from "@/lib/haptics";
import * as engagement from "@/engagement";
import { driveMinutes, HOLD_MIN, rankRescues, REWARD_EUR, scoreRescue } from "./logic";
import type { LatLon, RescueDest, RescueStage, ScoredRescue, Vehicle } from "./types";

export type RescueFlow = {
  /** Vehicles with already-rescued cars moved to their destination (and no longer rescue cars). Render these. */
  cars: Vehicle[];
  /** Rescue offers within walking distance of `me`, best first. */
  nearby: ScoredRescue[];
  /** Ids that get the €5 badge. */
  rescueIds: Set<number>;
  /** The offer for a vehicle if it has one for this user, else null. */
  offerFor: (v: Vehicle | null | undefined) => ScoredRescue | null;
  stage: RescueStage;
  /** The accepted rescue (numbers frozen at accept time). */
  active: ScoredRescue | null;
  startedAt: number;
  accept: (o: ScoredRescue) => void;
  arrived: () => void;
  parked: () => void;
  finish: () => void;
  cancel: () => void;
  /** Dashed line to draw: walk me -> car, or drive car -> destination. */
  route: LatLon[] | null;
  /** Destination ring to draw while driving. */
  dest: RescueDest | null;
  /** Where "you" are during the flow (at the car while driving, at the destination when done). */
  meNow: LatLon;
};

export function useRescueFlow(vehicles: Vehicle[], me: LatLon): RescueFlow {
  const [stage, setStage] = useState<RescueStage>("idle");
  const [active, setActive] = useState<ScoredRescue | null>(null);
  const [startedAt, setStartedAt] = useState(0);
  const [rescued, setRescued] = useState<Record<number, LatLon>>({});

  const cars = useMemo(
    () => vehicles.map((v) => (rescued[v.id] ? { ...v, ...rescued[v.id], rescue: undefined } : v)),
    [vehicles, rescued],
  );
  const nearby = useMemo(() => rankRescues(cars, me), [cars, me]);
  const rescueIds = useMemo(() => new Set(nearby.map((r) => r.id)), [nearby]);
  const offerFor = useCallback(
    (v: Vehicle | null | undefined) => (v && rescueIds.has(v.id) ? scoreRescue(v, me) : null),
    [rescueIds, me],
  );

  // Widget: whenever the nearby list changes.
  useEffect(() => {
    const best = nearby[0];
    void engagement.setWidgetData({
      nearbyCount: nearby.length,
      bestRewardEur: best ? REWARD_EUR : 0,
      bestWalkMin: nearby.length ? Math.max(1, Math.round(Math.min(...nearby.map((n) => n.walkMin)))) : 0,
      updatedAt: Date.now(),
      bestVehicleId: best?.id,
    });
  }, [nearby]);

  // Live Activity: keep minutes-left current while walking.
  useEffect(() => {
    if (stage !== "walking" || !active) return;
    const t = setInterval(() => {
      const left = Math.max(0, Math.round(active.walkMin - (Date.now() - startedAt) / 60000));
      void engagement.updateRescueActivity({ stage: "walking", minutesLeft: left });
    }, 60000);
    return () => clearInterval(t);
  }, [stage, active, startedAt]);

  const accept = useCallback((o: ScoredRescue) => {
    haptic("success");
    const now = Date.now();
    setActive(o);
    setStartedAt(now);
    setStage("walking");
    const walkMin = Math.max(1, Math.round(o.walkMin));
    void engagement
      .startRescueActivity({
        carModel: o.model,
        plate: o.plate,
        rewardEur: o.credit,
        walkMin,
        destinationName: o.rescue.dest?.name ?? "",
        expiresAt: now + HOLD_MIN * 60000,
      })
      .then(() => engagement.updateRescueActivity({ stage: "walking", minutesLeft: walkMin }));
  }, []);

  const arrived = useCallback(() => {
    if (!active?.rescue.dest) return;
    haptic("select");
    setStage("driving");
    void engagement.updateRescueActivity({ stage: "driving", minutesLeft: driveMinutes(active.rescue.dest.m) });
  }, [active]);

  const parked = useCallback(() => {
    const d = active?.rescue.dest;
    if (!active || !d) return;
    haptic("success");
    setStage("done");
    setRescued((r) => ({ ...r, [active.id]: { lat: d.lat, lon: d.lon } }));
    void engagement.updateRescueActivity({ stage: "done" }).then(() => engagement.endRescueActivity());
  }, [active]);

  const finish = useCallback(() => {
    setActive(null);
    setStage("idle");
  }, []);

  const cancel = useCallback(() => {
    setActive(null);
    setStage("idle");
    void engagement.endRescueActivity();
  }, []);

  const route: LatLon[] | null =
    stage === "walking" && active
      ? [me, active]
      : stage === "driving" && active?.rescue.dest
        ? [active, active.rescue.dest]
        : null;
  const dest = stage === "driving" && active?.rescue.dest ? active.rescue.dest : null;
  const meNow =
    stage === "driving" && active
      ? { lat: active.lat, lon: active.lon }
      : stage === "done" && active?.rescue.dest
        ? { lat: active.rescue.dest.lat, lon: active.rescue.dest.lon }
        : me;

  return { cars, nearby, rescueIds, offerFor, stage, active, startedAt, accept, arrived, parked, finish, cancel, route, dest, meNow };
}
