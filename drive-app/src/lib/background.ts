// Background refresh: every ~15 min while the OS allows, check whether a car worth rescuing is within walking distance
// of the user's last known location, and if so fire ONE local "rescue nearby" notification. Budget-gated to at most one
// per calendar day (MISSION: ~1/user/day, quiet day = silence). No server involved. Runs headless, so it's defined at
// module scope; lib/background.ts is imported from the root layout to register it.
import * as BackgroundTask from "expo-background-task";
import * as TaskManager from "expo-task-manager";
import * as Notifications from "expo-notifications";
import { cachedLocation } from "./location";
import { replayCars, rankRescues, stillPct } from "./rescue";
import { mins } from "./format";
import { WALK_NEAR } from "./config";
import { overDailyBudget, markSent } from "./notifications";

export const TASK = "rescue-nearby-check";

TaskManager.defineTask(TASK, async () => {
  try {
    const me = cachedLocation();
    if (!me) return BackgroundTask.BackgroundTaskResult.Success; // no location yet
    if (overDailyBudget()) return BackgroundTask.BackgroundTaskResult.Success; // quiet: already pushed today

    const ranked = rankRescues(replayCars(), me);
    const best = ranked[0];
    if (!best || best.walkMin > WALK_NEAR) return BackgroundTask.BackgroundTaskResult.Success; // nothing worth it nearby

    await Notifications.scheduleNotificationAsync({
      content: {
        title: `€${best.credit} rescue near you`,
        body: `${best.model} — a ${mins(best.walkMin)}-min walk. ${stillPct(best.stillThere)}% still there, money back if gone.`,
        data: { car: best.id },
      },
      trigger: null, // now
    });
    markSent();
    return BackgroundTask.BackgroundTaskResult.Success;
  } catch {
    return BackgroundTask.BackgroundTaskResult.Failed;
  }
});

/** Idempotent; safe to call on every launch. Needs notification permission to be useful. */
export async function registerBackgroundCheck() {
  try {
    const status = await BackgroundTask.getStatusAsync();
    if (status === BackgroundTask.BackgroundTaskStatus.Restricted) return;
    const already = await TaskManager.isTaskRegisteredAsync(TASK);
    if (!already) await BackgroundTask.registerTaskAsync(TASK, { minimumInterval: 15 });
  } catch (e) {
    console.info("background: not registered", e);
  }
}
