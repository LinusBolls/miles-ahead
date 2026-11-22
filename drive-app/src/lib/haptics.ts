// Haptic feedback, fire and forget (copied from musikraten's lib/haptics.ts).
import { Platform } from "react-native";
import * as Haptics from "expo-haptics";

type Kind = "press" | "select" | "success" | "error" | "warning";

/** Resolves once it was played. */
export function haptic(kind: Kind): Promise<void> {
  if (Platform.OS === "web") return Promise.resolve();
  const done =
    kind === "press"
      ? Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium)
      : kind === "select"
        ? Haptics.selectionAsync()
        : Haptics.notificationAsync(
            kind === "success"
              ? Haptics.NotificationFeedbackType.Success
              : kind === "error"
                ? Haptics.NotificationFeedbackType.Error
                : Haptics.NotificationFeedbackType.Warning,
          );
  return done.catch(() => {});
}
