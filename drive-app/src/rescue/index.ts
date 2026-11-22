// Rescue feature — public surface for host screens (temporary host: src/app/index.tsx; MILES replica: src/miles/).
//   const { doc } = useFleet();                         // vehicles.json (schema in ./types.ts)
//   const flow = useRescueFlow(doc.vehicles, me);       // offers, stage machine, engagement calls
//   map: vehicles={flow.cars}  renderMarkerOverlay={(v) => flow.rescueIds.has(v.id) ? <RescueBadge selected={v.id===sel}/> : null}
//        draw flow.route (dashed) and flow.dest (ring) if the map supports it; "you" = flow.meNow
//   sheet slot: <RescuePanel flow={flow} vehicle={selectedVehicle} />
export * from "./types";
export { useFleet, BUNDLED, FLEET_URL, isVan, rangeKm } from "./fleet";
export {
  REWARD_EUR,
  RESCUE_WALK_MAX,
  STILL_THERE,
  HOLD_MIN,
  rankRescues,
  scoreRescue,
  offerLine,
  stillPct,
  hours,
  walkFrom,
  driveMinutes,
} from "./logic";
export { useRescueFlow, type RescueFlow } from "./useRescueFlow";
export { RescueBadge } from "./RescueBadge";
export { RescuePanel, RescueOfferCard, WalkingPanel, DrivingPanel, DonePanel } from "./RescuePanel";
export { rescueColors } from "./theme";
