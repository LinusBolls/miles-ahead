// MILES-style concept screens (src/miles/), previewable standalone at /miles and /miles/search.
import { Stack } from "expo-router";

export default function MilesLayout() {
  return (
    <>
      {/* hide the parent stack's header for this group */}
      <Stack.Screen options={{ headerShown: false }} />
      <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: "#fff" } }} />
    </>
  );
}
