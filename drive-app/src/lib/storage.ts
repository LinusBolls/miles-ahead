// Small per-install values (the "I did it" client token, the last known location): a JSON file in the app's documents.
// Losing them is harmless.
import { Platform } from "react-native";
import { File, Paths } from "expo-file-system";

const isWeb = Platform.OS === "web";
const file = () => new File(Paths.document, "fuelback.json");

function read(): Record<string, string> {
  try {
    if (isWeb) return JSON.parse(localStorage.getItem("fuelback") ?? "{}");
    const f = file();
    return f.exists ? JSON.parse(f.textSync()) : {};
  } catch {
    return {};
  }
}

export function get(key: string): string | undefined {
  return read()[key];
}

export function set(key: string, value: string) {
  try {
    const all = JSON.stringify({ ...read(), [key]: value });
    if (isWeb) {
      localStorage.setItem("fuelback", all);
      return;
    }
    const f = file();
    if (!f.exists) f.create();
    f.write(all);
  } catch {}
}

/** A stable client token, so a double "I did it" from the same install is deduped (honour system). */
export function clientToken(): string {
  let t = get("token");
  if (!t) {
    t = Math.random().toString(36).slice(2) + Date.now().toString(36);
    set("token", t);
  }
  return t;
}
