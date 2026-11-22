// Floating map controls: round black menu button, "Hilfe" pill, round white search/locate buttons.
// All inert except search (navigates) and locate (recentres).
import { Pressable, StyleSheet, Text, View } from "react-native";
import { m, shadow } from "../theme";
import { HelpIcon, LocateIcon, MenuIcon, SearchIcon } from "./icons";

export function MenuButton({ onPress }: { onPress?: () => void }) {
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [styles.menu, pressed && styles.pressed]} accessibilityLabel="Menü">
      <MenuIcon size={26} />
    </Pressable>
  );
}

export function HelpPill({ onPress }: { onPress?: () => void }) {
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [styles.help, shadow, pressed && styles.pressed]} accessibilityLabel="Hilfe">
      <HelpIcon size={23} />
      <Text style={styles.helpText}>Hilfe</Text>
    </Pressable>
  );
}

export function RoundButton({ kind, onPress }: { kind: "search" | "locate"; onPress?: () => void }) {
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [styles.round, shadow, pressed && styles.pressed]}
      accessibilityLabel={kind === "search" ? "Suchen" : "Mein Standort"}
    >
      {kind === "search" ? <SearchIcon size={25} /> : <LocateIcon size={23} />}
    </Pressable>
  );
}

export function MapControlsColumn({ children }: { children: React.ReactNode }) {
  return <View style={styles.col}>{children}</View>;
}

const styles = StyleSheet.create({
  menu: {
    width: 50,
    height: 50,
    borderRadius: 25,
    backgroundColor: m.black,
    alignItems: "center",
    justifyContent: "center",
  },
  help: {
    height: 46,
    paddingLeft: 10,
    paddingRight: 16,
    borderRadius: 23,
    backgroundColor: m.white,
    flexDirection: "row",
    alignItems: "center",
    gap: 9,
  },
  helpText: { fontSize: 16, fontWeight: "600", color: m.black },
  round: {
    width: 54,
    height: 54,
    borderRadius: 27,
    backgroundColor: m.white,
    alignItems: "center",
    justifyContent: "center",
  },
  col: { gap: 12, alignItems: "center" },
  pressed: { opacity: 0.75 },
});
