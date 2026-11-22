// Native map pins for the MILES-style map (drawn with Views; web draws the same shapes on canvas).
import { StyleSheet, Text, View } from "react-native";
import { m } from "../theme";

export function CarPin({ selected }: { selected: boolean }) {
  const s = selected ? 1.3 : 1;
  return (
    <View style={[styles.wrap, { transform: [{ scale: s }] }]}>
      <View style={styles.head}>
        <Text style={styles.mark}>M</Text>
      </View>
      <View style={styles.tail} />
    </View>
  );
}

export function ClusterPin({ count }: { count: number }) {
  const d = count >= 100 ? 46 : count >= 10 ? 40 : 34;
  return (
    <View style={[styles.cluster, { width: d, height: d, borderRadius: d / 2 }]}>
      <Text style={styles.clusterText}>{count}</Text>
    </View>
  );
}

export function DestPin({ name }: { name: string }) {
  return (
    <View style={styles.wrap}>
      <View style={styles.destLabel}>
        <Text style={styles.destText} numberOfLines={1}>
          {name}
        </Text>
      </View>
      <View style={styles.destRing}>
        <View style={styles.destDot} />
      </View>
    </View>
  );
}

export function MeDot() {
  return (
    <View style={styles.me}>
      <View style={styles.meInner} />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: "center", paddingTop: 2 },
  head: {
    width: 30,
    height: 30,
    borderRadius: 15,
    backgroundColor: m.black,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1.5,
    borderColor: m.white,
  },
  mark: { color: m.white, fontWeight: "900", fontStyle: "italic", fontSize: 15, marginTop: -1 },
  tail: {
    width: 0,
    height: 0,
    marginTop: -2,
    borderLeftWidth: 5,
    borderRightWidth: 5,
    borderTopWidth: 8,
    borderLeftColor: "transparent",
    borderRightColor: "transparent",
    borderTopColor: m.black,
  },
  destLabel: { backgroundColor: m.black, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 8, marginBottom: 4, maxWidth: 180 },
  destText: { color: m.white, fontWeight: "700", fontSize: 12 },
  destRing: {
    width: 24,
    height: 24,
    borderRadius: 12,
    borderWidth: 3,
    borderColor: m.locate,
    backgroundColor: "rgba(41,121,255,0.15)",
    alignItems: "center",
    justifyContent: "center",
  },
  destDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: m.locate },
  cluster: { backgroundColor: m.black, alignItems: "center", justifyContent: "center" },
  clusterText: { color: m.white, fontWeight: "700", fontSize: 15 },
  me: {
    width: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: "rgba(41,121,255,0.18)",
    alignItems: "center",
    justifyContent: "center",
  },
  meInner: { width: 14, height: 14, borderRadius: 7, backgroundColor: m.locate, borderWidth: 2.5, borderColor: m.white },
});
