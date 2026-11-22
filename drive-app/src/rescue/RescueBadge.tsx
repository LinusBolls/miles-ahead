// The €5 marker badge. For a host map's renderMarkerOverlay(vehicle): render <RescueBadge/> when
// flow.rescueIds.has(vehicle.id). Blue pill with a pointer; inverted when selected.
import { StyleSheet, Text, View } from "react-native";
import { rescueColors } from "./theme";

export function RescueBadge({ amount = 5, selected = false }: { amount?: number; selected?: boolean }) {
  return (
    <View style={[s.wrap, selected && { transform: [{ scale: 1.15 }] }]} accessibilityLabel={`Rescue, €${amount} credit`}>
      <View style={[s.pill, selected && s.pillSel]}>
        <Text style={[s.text, selected && s.textSel]}>€{amount}</Text>
      </View>
      <View style={s.tail} />
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { alignItems: "center" },
  pill: {
    height: 30,
    minWidth: 46,
    paddingHorizontal: 10,
    borderRadius: 15,
    backgroundColor: rescueColors.accent,
    borderWidth: 2,
    borderColor: "#fff",
    alignItems: "center",
    justifyContent: "center",
    shadowColor: "#000",
    shadowOpacity: 0.2,
    shadowRadius: 5,
    shadowOffset: { width: 0, height: 2 },
    elevation: 4,
  },
  pillSel: { backgroundColor: "#fff", borderColor: rescueColors.accent },
  text: { color: "#fff", fontWeight: "800", fontSize: 14, letterSpacing: -0.2 },
  textSel: { color: rescueColors.accent },
  tail: {
    width: 0,
    height: 0,
    marginTop: -1,
    borderLeftWidth: 5,
    borderRightWidth: 5,
    borderTopWidth: 7,
    borderLeftColor: "transparent",
    borderRightColor: "transparent",
    borderTopColor: rescueColors.accent,
  },
});
