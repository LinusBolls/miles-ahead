// ?embed=1: the PWA running inside the landing page's CSS iPhone frame (iframe, 390x844). The frame draws its own
// status bar / Dynamic Island and home indicator, so we pad with fixed insets instead of env(safe-area-inset-*),
// and hide anything that would navigate out of the iframe or need permissions (GPS).
import { Platform } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

export const EMBED =
  Platform.OS === "web" &&
  typeof window !== "undefined" &&
  new URLSearchParams(window.location.search).get("embed") === "1";

if (EMBED) document.documentElement.setAttribute("data-embed", "1"); // CSS hooks in public/index.html

const FRAME_INSETS = { top: 54, bottom: 34, left: 0, right: 0 };

/** Safe-area insets: real ones (env() on the web PWA, native on iOS), or the iPhone frame's when embedded. */
export function useInsets() {
  const real = useSafeAreaInsets();
  return EMBED ? FRAME_INSETS : real;
}
