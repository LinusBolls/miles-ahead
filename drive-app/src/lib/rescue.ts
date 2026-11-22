// Moved to src/rescue (logic.ts). Re-exported for the headless background check (lib/background.ts).
import { BUNDLED } from "@/rescue/fleet";
import type { Vehicle } from "@/rescue/types";
export { rankRescues, scoreRescue, offerLine, stillPct, REWARD_EUR, STILL_THERE, HOLD_MIN, hours } from "@/rescue/logic";
export type { ScoredRescue } from "@/rescue/types";

/** Bundled snapshot's rescue cars. */
export function replayCars(): Vehicle[] {
  return BUNDLED.vehicles.filter((v) => v.rescue);
}
