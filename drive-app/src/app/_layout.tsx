// Root: providers, OTA updates, the native stack, and a one-time setup of notifications + background refresh.
import { useEffect } from "react";
import { Platform, Pressable, StyleSheet, Text, View } from "react-native";
import { StatusBar } from "expo-status-bar";
import { Stack, type ErrorBoundaryProps } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { colors } from "@/lib/theme";
import { useUpdates } from "@/lib/updates";
import { useRescueEngagement } from "@/engagement";
import { ensureNotificationPermission, registerRemoteToken } from "@/lib/notifications";

SplashScreen.preventAutoHideAsync().catch(() => {});

export function ErrorBoundary({ error, retry }: ErrorBoundaryProps) {
  // Keep the app alive on a screen crash with a way back, rather than a white screen.
  return (
    <View style={styles.boundary}>
      <Text style={styles.boundaryTitle}>Something broke</Text>
      <Text style={styles.boundaryMsg}>{error.message}</Text>
      <Pressable style={styles.boundaryBtn} onPress={retry}>
        <Text style={styles.boundaryBtnText}>Try again</Text>
      </Pressable>
    </View>
  );
}

export default function Root() {
  useUpdates();
  useRescueEngagement(); // push-tap / deep-link routing to /rescue/<id> (native agent)

  useEffect(() => {
    SplashScreen.hideAsync().catch(() => {});
    if (Platform.OS === "web") return; // native-only modules below
    (async () => {
      const allowed = await ensureNotificationPermission();
      // lib/background pulls in expo-background-task (native only); load it only off the web.
      const { registerBackgroundCheck } = await import("@/lib/background");
      await registerBackgroundCheck();
      if (allowed) await registerRemoteToken();
    })();
  }, []);

  return (
    <GestureHandlerRootView style={styles.root}>
      <SafeAreaProvider>
        <StatusBar style="dark" />
        <Stack
          screenOptions={{
            contentStyle: { backgroundColor: colors.paper },
            headerStyle: { backgroundColor: colors.paper },
            headerTintColor: colors.ink,
            headerShadowVisible: false,
            headerTitleStyle: { fontWeight: "700" },
          }}
        >
          <Stack.Screen name="index" options={{ headerShown: false }} />
          <Stack.Screen name="rescue/[id]" options={{ headerShown: false, animation: "none" }} />
        </Stack>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.paper },
  boundary: { flex: 1, backgroundColor: colors.paper, alignItems: "center", justifyContent: "center", padding: 24, gap: 10 },
  boundaryTitle: { fontSize: 20, fontWeight: "800", color: colors.ink },
  boundaryMsg: { fontSize: 15, color: colors.ink2, textAlign: "center" },
  boundaryBtn: { marginTop: 8, backgroundColor: colors.accent, paddingHorizontal: 20, paddingVertical: 12, borderRadius: 14 },
  boundaryBtnText: { color: colors.accentOn, fontWeight: "700", fontSize: 16 },
});
