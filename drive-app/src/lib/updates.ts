// Silent OTA updates (EAS Update): checked when the app comes to the foreground, applied once it goes to the background,
// so the list is never reloaded away under the user. Nothing in development. Copied from musikraten's lib/updates.ts.
import { useEffect, useEffectEvent } from "react";
import { AppState } from "react-native";
import * as Updates from "expo-updates";

export function useUpdates() {
  const { isUpdatePending, isChecking, isDownloading, downloadedUpdate } = Updates.useUpdates();

  const applyPending = useEffectEvent(() => {
    if (!isUpdatePending || AppState.currentState !== "background") return;
    Updates.reloadAsync().catch((e: unknown) => console.warn("update: reload failed", e));
  });

  const check = useEffectEvent(async () => {
    if (isChecking || isDownloading) return;
    try {
      const result = await Updates.checkForUpdateAsync();
      if (result.isAvailable || result.isRollBackToEmbedded) await Updates.fetchUpdateAsync();
    } catch (e) {
      console.info("update: check failed", e);
    }
  });

  useEffect(() => {
    if (__DEV__ || !Updates.isEnabled) return;
    const subscription = AppState.addEventListener("change", (next) => {
      if (next === "active") void check();
      if (next === "background") applyPending();
    });
    return () => subscription.remove();
  }, []);

  useEffect(() => {
    if (!__DEV__ && Updates.isEnabled) applyPending();
  }, [isUpdatePending, downloadedUpdate?.updateId]);
}
