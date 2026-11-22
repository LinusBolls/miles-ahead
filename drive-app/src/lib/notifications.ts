// Notifications for Rescue. Two uses:
//   1. Local "rescue nearby" notifications fired by the background task (lib/background.ts) when a car worth rescuing is
//      near your last location — budget-gated to ~1/day, silent on quiet days. Fully server-free.
//   2. A production APNs device token is registered for future SERVER-SENT pushes (budget-gated per MISSION). The send
//      side is a separate piece: the token is stored locally and would be POSTed to the ops backend once /push exists.
//      SERVER TODO: add `POST /push {token, platform}`, store tokens, and a sender that budgets net value per user/day.
import { Platform } from "react-native";
import * as Notifications from "expo-notifications";
import * as storage from "./storage";

if (Platform.OS === "ios") {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: false,
      shouldSetBadge: false,
    }),
  });
}

/** Asks once (later launches just read the answer). Returns whether notifications are allowed. */
export async function ensureNotificationPermission(): Promise<boolean> {
  if (Platform.OS !== "ios") return false;
  const current = await Notifications.getPermissionsAsync();
  if (current.granted) return true;
  if (!current.canAskAgain) return false;
  const asked = await Notifications.requestPermissionsAsync();
  return asked.granted;
}

/** Registers the production APNs token and stores it. No server call yet (see SERVER TODO above). */
export async function registerRemoteToken(): Promise<string | null> {
  if (Platform.OS !== "ios") return null;
  try {
    const { data } = await Notifications.getDevicePushTokenAsync();
    if (typeof data === "string") {
      storage.set("apnsToken", data);
      console.info("push: APNs token registered (server send side is a TODO)");
      return data;
    }
  } catch (e) {
    console.info("push: token not available", e);
  }
  return null;
}

/**
 * Demo helper: schedule a single "rescue nearby" local notification a few seconds out, so the push experience can be
 * shown on TestFlight without the server. Respects the same once-a-day budget as the background task.
 */
export async function scheduleNearbyRescueDemo(args: {
  model: string;
  credit: number;
  walkMin: number;
  stillPct: number;
  carId: number;
  delaySec?: number;
}): Promise<"scheduled" | "no-permission" | "budgeted"> {
  if (Platform.OS !== "ios") return "no-permission";
  const ok = await ensureNotificationPermission();
  if (!ok) return "no-permission";
  if (overDailyBudget()) return "budgeted";
  await Notifications.scheduleNotificationAsync({
    content: {
      title: `€${args.credit} rescue near you`,
      body: `${args.model} — a ${args.walkMin}-min walk. ${args.stillPct}% still there, money back if gone.`,
      data: { car: args.carId },
    },
    trigger: args.delaySec ? { seconds: args.delaySec } : null,
  } as any);
  markSent();
  return "scheduled";
}

// ---- budget: at most one push per calendar day (MISSION: ~1/user/day, quiet day = silence) ----
export function overDailyBudget(): boolean {
  const raw = storage.get("lastPushDay");
  return raw === today();
}
export function markSent() {
  storage.set("lastPushDay", today());
}
function today(): string {
  return new Date().toISOString().slice(0, 10);
}
