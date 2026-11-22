// Mandatory honesty marker on every concept screen: this is NOT the MILES app.
import { StyleSheet, Text, View, type ViewStyle } from "react-native";

export function ConceptTag({ style }: { style?: ViewStyle }) {
  return (
    <View pointerEvents="none" style={[styles.tag, style]} accessibilityLabel="Concept demo, not the MILES app">
      <Text style={styles.text}>Concept · demo</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  tag: {
    position: "absolute",
    zIndex: 100,
    backgroundColor: "rgba(17,18,22,0.72)",
    paddingHorizontal: 7,
    paddingVertical: 2.5,
    borderRadius: 5,
  },
  text: { color: "#fff", fontSize: 10, fontWeight: "600", letterSpacing: 0.2 },
});
