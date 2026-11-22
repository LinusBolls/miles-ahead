import type { ExpoConfig } from "expo/config";

// Fuelback (MILES x Rescue): the rider side of the MILES fleet. A map of ONLY the cars worth rescuing near you — cars
// predicted to strand (sit idle a day+) that you move a short distance to a demand area for €5 ride credit. Unofficial,
// not affiliated with MILES.
//
// Push notifications need a provisioning profile with the aps-environment entitlement, which EAS generates with an
// App Store Connect API key (cloud signing). PUSH=0 builds without the push entitlement, for a wildcard dev profile.
const push = process.env.PUSH !== "0";

// Widget (WidgetKit) + Live Activity (ActivityKit) are native Swift targets added via @bacons/apple-targets (targets/),
// driven by the local module modules/rescue-engagement. ON by default: the OTA fingerprint must be computed with the
// same plugin list as the binary, so `scripts/ota` and `eas build` must agree. APPLE_TARGETS=0 opts out.
const appleTargets = process.env.APPLE_TARGETS !== "0";

// Shared keychain group for app -> widget data (instead of an App Group, which EAS can't link with an ASC API key).
// Every provisioning profile already allows "<TeamID>.*" keychain groups, so this needs no portal change.
const sharedKeychainGroup = "A5X77AGYX4.so.bolls.fuelback.shared";

// The EAS project id (from `eas init`). OTA updates resolve the right project from it. Left undefined before the
// project exists so `eas init` can create and link it.
const projectId = process.env.EAS_PROJECT_ID || "15e80931-e1dc-40c9-9e50-26f05148299c";
const hasProject = projectId !== "__PROJECT_ID__";

const config: ExpoConfig = {
  name: "Finderlohn",
  slug: "fuelback",
  scheme: "fuelback",
  version: "1.0.0",
  orientation: "portrait",
  icon: "./assets/icon.png",
  userInterfaceStyle: "light",
  backgroundColor: "#F4F7F6",
  ios: {
    supportsTablet: true,
    bundleIdentifier: "so.bolls.fuelback",
    appleTeamId: "A5X77AGYX4",
    // iOS uses Apple Maps via react-native-maps (no API key, no Google pod). Google Maps on iOS is no longer
    // supported by react-native-maps (the react-native-google-maps podspec was removed) nor by expo-maps
    // (Google there is Android-only). Standardized cross-platform default: Apple on iOS, Google on Android.
    config: { usesNonExemptEncryption: false },
    ...(appleTargets ? { entitlements: { "keychain-access-groups": [sharedKeychainGroup] } } : {}),
    infoPlist: {
      // Background refresh + background location: alert you when a car worth rescuing appears within walking distance.
      UIBackgroundModes: ["fetch", "remote-notification", "location"],
      ITSAppUsesNonExemptEncryption: false,
      // Live Activity on the Lock Screen / Dynamic Island while heading to a rescue car.
      NSSupportsLiveActivities: true,
    },
  },
  plugins: [
    "expo-router",
    [
      "expo-location",
      {
        locationWhenInUsePermission:
          "Rescue uses your location to show cars worth rescuing within walking distance of you.",
        locationAlwaysAndWhenInUsePermission:
          "Rescue uses your location in the background to alert you when a car worth rescuing appears within walking distance — only if you turn on nearby-rescue alerts.",
        isIosBackgroundLocationEnabled: true,
      },
    ],
    // TestFlight/App Store builds get APNs production tokens.
    ...(push ? [["expo-notifications", { mode: "production" }] as [string, object]] : []),
    "expo-background-task",
    ["expo-splash-screen", { backgroundColor: "#F4F7F6", image: "./assets/splash-icon.png", imageWidth: 140 }],
    // Native Swift targets (widget + live activity); only when explicitly building them.
    ...(appleTargets ? ["@bacons/apple-targets"] : []),
  ],
  extra: { push, ...(hasProject ? { eas: { projectId } } : {}) },
  owner: "bolls",
  runtimeVersion: { policy: "fingerprint" },
  ...(hasProject
    ? {
        updates: {
          url: `https://u.expo.dev/${projectId}`,
          checkAutomatically: "ON_LOAD" as const,
          fallbackToCacheTimeout: 0,
          requestHeaders: { "expo-channel-name": "production" },
        },
      }
    : {}),
  web: { bundler: "metro", output: "single", favicon: "./assets/icon.png" },
  // Web-only: the PWA export sets EXPO_WEB_BASE_URL=/app. Unset (native builds) -> undefined -> dropped from config.
  experiments: { typedRoutes: true, baseUrl: process.env.EXPO_WEB_BASE_URL },
};

export default config;
