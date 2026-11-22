// Design tokens for the MILES-style concept screens (src/miles/).
// Colours/sizes were measured from public App Store screenshots and the app's public resource values
// (colour hex codes only). No MILES image or font files are bundled: icons are drawn here in SVG and the
// brand typeface (a commercial font) is substituted with system fonts.
import { Platform } from "react-native";

export const m = {
  black: "#000000",
  ink: "#111216",
  ink2: "#3c3e49", // MILES "grayButton"
  muted: "#6b6f7e",
  faint: "#9aa0b0",
  white: "#ffffff",
  mapBg: "#eceef2",
  card: "#f1f3f8", // light blue-grey card surface (vehicle list, tariff cards)
  line: "#d6dae3",
  lineStrong: "#c4c9d4",
  blue: "#2a8cf0", // links / distance chips / active tab
  blueChipBg: "#e3eefb",
  locate: "#2979ff",
  navy: "#1c2033", // floating "Filters" pill
  green: "#1fcf9e",
  hub: "#1565c0",
};

export const radius = { card: 10, button: 8, pill: 999, sheet: 16 };

/** Condensed heavy face for plates and headlines (substitute for the brand's compressed black cut). */
export const condensed = Platform.select({
  ios: { fontFamily: "AvenirNextCondensed-Heavy" as const },
  web: {
    fontFamily: "'Avenir Next Condensed', 'HelveticaNeue-CondensedBlack', 'Roboto Condensed', 'Arial Narrow', sans-serif",
    fontWeight: "800" as const,
    fontStretch: "condensed",
  } as any,
  default: { fontWeight: "900" as const },
});

export const shadow = Platform.select({
  web: { boxShadow: "0 2px 10px rgba(0,0,0,0.14)" } as any,
  default: {
    shadowColor: "#000",
    shadowOpacity: 0.14,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 2 },
    elevation: 4,
  },
});

export const sheetShadow = Platform.select({
  web: { boxShadow: "0 -2px 16px rgba(0,0,0,0.10)" } as any,
  default: {
    shadowColor: "#000",
    shadowOpacity: 0.1,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: -2 },
    elevation: 8,
  },
});
