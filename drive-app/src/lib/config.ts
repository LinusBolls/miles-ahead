// Endpoints and the outbound links the app builds. The API base can be overridden at build time
// (EXPO_PUBLIC_API) for pointing at a local miles-drive; it defaults to the live service.
import Constants from "expo-constants";
import * as Application from "expo-application";
import * as Updates from "expo-updates";

export const API = (process.env.EXPO_PUBLIC_API || "https://miles.bolls.dev/drive/api/").replace(/\/?$/, "/");

// MILES' universal/app link (apple-app-site-association covers "*"): opens the MILES app if installed, else Safari.
export const MILES_APP_LINK = "https://api.app.miles-mobility.com/mobile/Screen/MapScreen";
export const MILES_APPSTORE = "https://apps.apple.com/de/app/miles-carsharing-vansharing/id1220185947";
export const MILES_PLAY = "https://play.google.com/store/apps/details?id=com.driveby.app";

/** Apple Maps directions to a point. mode "walk" | "drive". */
export const mapsHref = (lat: number, lon: number, mode: "walk" | "drive"): string =>
  `https://maps.apple.com/?daddr=${lat},${lon}&dirflg=${mode === "walk" ? "w" : "d"}`;

export const VERSION_LABEL = `v${Application.nativeApplicationVersion ?? Constants.expoConfig?.version ?? "dev"}${
  Application.nativeBuildVersion ? ` (${Application.nativeBuildVersion})` : ""
}${Updates.updateId ? ` · ${Updates.updateId.slice(0, 8)}` : ""}`;

// Constants used by the scoring, ported from drive.js.
export const WALK_M_PER_MIN = 80;
export const WALK_DETOUR = 1.3; // straight line -> walking distance
export const WALK_NEAR = 15; // minutes: default list
export const WALK_FAR = 30; // minutes: "show farther"
export const PUMP_MIN = 10; // our guess at time at the pump
export const BERLIN = { lat: 52.515, lon: 13.4 };

export const PLACES = {
  cic: { lat: 52.49373, lon: 13.44611, name: "CIC Berlin", src: "cic" as const },
  alex: { lat: 52.52192, lon: 13.41321, name: "Alexanderplatz", src: "alex" as const },
};
