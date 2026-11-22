// Rescue engagement surfaces (iOS): Live Activity, home-screen widget data, Expo push registration + push-tap routing.
// Native side: modules/rescue-engagement (ActivityKit + widget data) and targets/widget (SwiftUI for both surfaces).
// Web twin: index.web.ts (no-ops). Every call is best-effort: a failure logs and resolves, it never breaks the UI.
//
// HONESTY: the data passed in here comes from the app's demo/replay rescue set. The widget and Live Activity label
// themselves "Demo data" / "concept demo"; nothing here claims live MILES data.
import { useEffect } from "react";
import { Platform, Share } from "react-native";
import { requireOptionalNativeModule } from "expo";
import Constants from "expo-constants";
import * as Linking from "expo-linking";
import * as Notifications from "expo-notifications";
import { router, type Href } from "expo-router";
import * as storage from "@/lib/storage";

type NativeRescue = {
  areActivitiesEnabled(): boolean;
  startActivity(
    carModel: string,
    plate: string,
    rewardEur: number,
    walkMin: number,
    destinationName: string,
    expiresAtMs: number,
  ): Promise<string | null>;
  updateActivity(stage: string, minutesLeft: number): Promise<boolean>;
  endActivity(): Promise<void>;
  setWidgetData(json: string): boolean;
};

// Optional: a binary built before this module existed (or Expo Go) just gets no-ops instead of a crash.
const native = Platform.OS === "ios" ? requireOptionalNativeModule<NativeRescue>("RescueEngagement") : null;

type DateLike = number | string | Date;
const toMs = (d: DateLike): number => (d instanceof Date ? d.getTime() : typeof d === "number" ? d : Date.parse(d));

// ---------------------------------------------------------------- Live Activity

export async function startRescueActivity(args: {
  carModel: string;
  plate: string;
  rewardEur: number;
  walkMin: number;
  destinationName: string;
  /** When the reservation hold ends (shown as a countdown while walking). Default: 15 min from now. */
  expiresAt?: DateLike;
}): Promise<void> {
  if (!native) return;
  try {
    const exp = args.expiresAt != null ? toMs(args.expiresAt) : NaN;
    const expiresAtMs = Number.isFinite(exp) ? exp : Date.now() + 15 * 60_000;
    const id = await native.startActivity(
      args.carModel,
      args.plate,
      args.rewardEur,
      args.walkMin,
      args.destinationName,
      expiresAtMs,
    );
    if (!id) console.info("engagement: Live Activities are disabled on this device");
  } catch (e) {
    console.warn("engagement: startRescueActivity failed", e);
  }
}

export async function updateRescueActivity(args: {
  stage: "walking" | "driving" | "done";
  minutesLeft?: number;
}): Promise<void> {
  if (!native) return;
  try {
    await native.updateActivity(args.stage, args.minutesLeft ?? 0);
  } catch (e) {
    console.warn("engagement: updateRescueActivity failed", e);
  }
}

/** Ends the activity; its last state (e.g. "Rescued · €5 credited") stays on the Lock Screen ~2 min. */
export async function endRescueActivity(): Promise<void> {
  if (!native) return;
  try {
    await native.endActivity();
  } catch (e) {
    console.warn("engagement: endRescueActivity failed", e);
  }
}

// ---------------------------------------------------------------- Widget

export async function setWidgetData(args: {
  nearbyCount: number;
  bestRewardEur: number;
  bestWalkMin: number;
  updatedAt: DateLike;
  /** Optional: widget tap opens fuelback://rescue/<id> for this car (otherwise the app's home). */
  bestVehicleId?: string | number;
}): Promise<void> {
  if (!native) return;
  try {
    const updated = toMs(args.updatedAt);
    const json = JSON.stringify({
      nearbyCount: Number(args.nearbyCount) || 0,
      bestRewardEur: Number(args.bestRewardEur) || 0,
      bestWalkMin: Number(args.bestWalkMin) || 0,
      updatedAt: Number.isFinite(updated) ? updated : Date.now(),
      ...(args.bestVehicleId != null ? { bestVehicleId: String(args.bestVehicleId) } : {}),
    });
    native.setWidgetData(json);
  } catch (e) {
    console.warn("engagement: setWidgetData failed", e);
  }
}

// ---------------------------------------------------------------- Push

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

let pending: Promise<string | null> | null = null;

/** Asks for permission (once) and returns this install's Expo push token ("ExponentPushToken[...]"), or null. */
export function registerForPush(): Promise<string | null> {
  if (Platform.OS !== "ios") return Promise.resolve(null);
  if (!pending) {
    pending = (async () => {
      try {
        let perm = await Notifications.getPermissionsAsync();
        if (!perm.granted && perm.canAskAgain) perm = await Notifications.requestPermissionsAsync();
        if (!perm.granted) return null;
        const projectId =
          (Constants.expoConfig?.extra as { eas?: { projectId?: string } } | undefined)?.eas?.projectId ??
          Constants.easConfig?.projectId;
        const { data } = await Notifications.getExpoPushTokenAsync(projectId ? { projectId } : undefined);
        storage.set("expoPushToken", data);
        console.info("push: Expo push token", data);
        return data;
      } catch (e) {
        console.warn("push: could not get Expo push token", e);
        pending = null; // allow a retry later (e.g. offline at launch)
        return null;
      }
    })();
  }
  return pending;
}

/** The last registered Expo push token, without prompting. */
export function getPushToken(): string | null {
  return storage.get("expoPushToken") ?? null;
}

/**
 * Demo helper: opens the iOS share sheet with this device's Expo push token (AirDrop/Message it to the laptop that
 * runs tools/send-rescue-push.mjs). Also reachable without any UI: open `fuelback://?pushtoken=1` in Safari.
 */
export async function showPushToken(): Promise<void> {
  const token = (await registerForPush()) ?? getPushToken();
  await Share.share({
    message: token ?? "No push token yet: allow notifications for this app in Settings, then try again.",
  }).catch(() => {});
}

// Push data contract: { url: "fuelback://rescue/<vehicleId>" }. Older local notifications carry { car: <id> }.
function pathFrom(data: Record<string, unknown> | undefined): string | null {
  if (!data) return null;
  if (typeof data.url === "string" && data.url) {
    const path = data.url.replace(/^fuelback:\/\//, "/");
    return path.startsWith("/") ? path : `/${path}`;
  }
  if (data.car != null) return `/rescue/${String(data.car)}`;
  return null;
}

let lastHandled: string | null = null;
function openFromResponse(response: Notifications.NotificationResponse | null) {
  if (!response) return;
  const id = response.notification.request.identifier;
  if (id === lastHandled) return;
  lastHandled = id;
  const path = pathFrom(response.notification.request.content.data as Record<string, unknown> | undefined);
  if (!path) return;
  try {
    router.push(path as Href);
  } catch (e) {
    console.warn("push: could not open", path, e);
  }
}

function maybeShowToken(url: string | null) {
  if (url && /[?&]pushtoken\b/.test(url)) void showPushToken();
}

/**
 * Mount ONCE in the root layout. Registers the push token, routes push taps (cold start + while running) to the
 * rescue card, and answers `fuelback://?pushtoken=1` with the share sheet.
 */
export function useRescueEngagement(): void {
  useEffect(() => {
    if (Platform.OS !== "ios") return;
    void registerForPush();
    // Cold start from a push tap: wait a tick so the navigator is mounted.
    const t = setTimeout(() => openFromResponse(Notifications.getLastNotificationResponse()), 50);
    const sub = Notifications.addNotificationResponseReceivedListener(openFromResponse);
    Linking.getInitialURL().then(maybeShowToken).catch(() => {});
    const linkSub = Linking.addEventListener("url", ({ url }) => maybeShowToken(url));
    return () => {
      clearTimeout(t);
      sub.remove();
      linkSub.remove();
    };
  }, []);
}
