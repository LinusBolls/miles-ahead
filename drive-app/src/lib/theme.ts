// MILES-style palette: black/white UI on a light grey map, one blue accent (MILES uses it for distance chips).
// Rescue uses that same blue so the feature reads as native, not bolted on. No other hues.
export const colors = {
  paper: "#FFFFFF",
  card: "#FFFFFF",
  ink: "#000000",
  ink2: "#3C4048",
  ink3: "#7A808A",
  line: "#E3E6EB",
  chip: "#F1F3F7", // icon chips + tariff cards
  accent: "#1F6FEB", // MILES-ish blue: distance chips, rescue
  accentSoft: "#E6EFFD",
  accentOn: "#FFFFFF",
  me: "#000000",
  bad: "#B42318",
  // legacy keys still read by a few native-only modules
  accentInk: "#1F6FEB",
  fuel: "#1F6FEB",
};

export const radius = { sm: 10, md: 14, lg: 22, pill: 999 };
export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24 };
