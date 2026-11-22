// Selected-car bottom sheet in the MILES app's layout: plate + model, range + fuel type, car art,
// km-tariff card + "more options" card, primary "Fahrzeug auswählen" and secondary "Reservieren".
// Every button is INERT (concept demo: nothing books, reserves or pays).
// Extension point: `slot` renders above the buttons (Rescue puts its offer card there).
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { condensed, m, radius, sheetShadow } from "../theme";
import { displayModel, displayPlate, euro, euroShort, fuelLabel, isVan, rangeKm, type Vehicle } from "../data";
import { CarArt, ChevronRight, DropIcon, LocateIcon, RangeIcon, BoltIcon } from "./icons";

export function VehicleSheet({
  vehicle,
  bottomPad,
  slot,
  onPrimary,
  mode = "full",
}: {
  vehicle: Vehicle;
  bottomPad: number;
  slot?: ReactNode;
  onPrimary?: () => void;
  /** full = the app's sheet; compact = head + facts + slot (no tariffs/booking); head = plate/model + slot. */
  mode?: "full" | "compact" | "head";
}) {
  const v = vehicle;
  const full = mode === "full";
  // Inert booking buttons still answer a tap, so nobody thinks the demo is broken.
  const [toast, setToast] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inert = () => {
    setToast(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setToast(false), 2400);
  };
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);
  return (
    <View style={[styles.sheet, sheetShadow, { paddingBottom: bottomPad + 12 }]}>
      <View style={styles.head}>
        <View style={styles.headSide} />
        <View style={styles.headMid}>
          <Text style={[styles.plate, condensed]}>{displayPlate(v)}</Text>
          <Text style={styles.model}>{displayModel(v)}</Text>
        </View>
        <View style={[styles.headSide, { alignItems: "flex-end" }]}>
          <LocateIcon size={24} color={m.black} />
        </View>
      </View>

      {mode !== "head" ? (
      <View style={styles.infoRow}>
        <View style={{ gap: 10, flex: 1 }}>
          <View style={styles.fact}>
            <View style={styles.factIcon}>
              <RangeIcon size={17} />
            </View>
            <Text style={styles.factStrong}>
              ~{rangeKm(v)}km <Text style={styles.factLight}>({v.pct}%)</Text>
            </Text>
          </View>
          <View style={styles.fact}>
            <View style={styles.factIcon}>{v.ev ? <BoltIcon size={15} /> : <DropIcon size={17} />}</View>
            <Text style={styles.factStrong}>{fuelLabel(v)}</Text>
          </View>
        </View>
        <CarArt width={mode === "compact" ? 120 : 150} van={isVan(v)} />
      </View>
      ) : null}

      {full ? (
      <View style={styles.tariffs}>
        <View style={[styles.tariff, styles.tariffSel]}>
          <Text style={styles.tLabel}>Km-Tarif</Text>
          <Text style={styles.tPrice}>{euro(v.kmPrice)}/km</Text>
          <Text style={styles.tSub}>+ {euroShort(v.unlock)} Unlock Fee</Text>
        </View>
        <View style={[styles.tariff, styles.tariffAlt]}>
          <View style={{ flex: 1 }}>
            <Text style={styles.tLabel}>Mehr Optionen</Text>
            <Text style={styles.tOpt}>Stunden- &{"\n"}Tagestarife</Text>
          </View>
          <ChevronRight size={16} />
        </View>
      </View>
      ) : null}

      {slot ? <View style={{ marginTop: 12 }}>{slot}</View> : null}

      {full ? (
      <>
      <View style={styles.divider} />
      {toast ? (
        <View style={styles.toast} accessibilityLiveRegion="polite">
          <Text style={styles.toastText}>Concept: booking isn't part of this demo</Text>
        </View>
      ) : null}
      <Pressable onPress={onPrimary ?? inert} style={({ pressed }) => [styles.primary, pressed && { opacity: 0.85 }]}>
        <Text style={styles.primaryText}>Fahrzeug auswählen</Text>
      </Pressable>
      <Pressable onPress={inert} style={({ pressed }) => [styles.secondary, pressed && { opacity: 0.7 }]}>
        <Text style={styles.secondaryText}>Reservieren</Text>
      </Pressable>
      </>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  sheet: {
    backgroundColor: m.white,
    borderTopLeftRadius: radius.sheet,
    borderTopRightRadius: radius.sheet,
    paddingHorizontal: 18,
    paddingTop: 18,
  },
  head: { flexDirection: "row", alignItems: "flex-start" },
  headSide: { width: 40 },
  headMid: { flex: 1, alignItems: "center" },
  plate: { fontSize: 21, color: m.black, letterSpacing: 0.2 },
  model: { fontSize: 15.5, color: m.ink2, marginTop: 1 },
  infoRow: { flexDirection: "row", alignItems: "center", marginTop: 10 },
  fact: { flexDirection: "row", alignItems: "center", gap: 10 },
  factIcon: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: m.card,
    alignItems: "center",
    justifyContent: "center",
  },
  factStrong: { fontSize: 15.5, fontWeight: "600", color: m.black },
  factLight: { fontWeight: "400", color: m.ink2 },
  tariffs: { flexDirection: "row", gap: 10, marginTop: 14 },
  tariff: { flex: 1, borderRadius: radius.card, paddingHorizontal: 13, paddingVertical: 9, minHeight: 80 },
  tariffSel: { borderWidth: 2, borderColor: m.black, backgroundColor: m.card },
  tariffAlt: { backgroundColor: m.card, flexDirection: "row", alignItems: "center", borderWidth: 2, borderColor: "transparent" },
  tLabel: { fontSize: 14.5, color: m.ink2 },
  tPrice: { fontSize: 18, fontWeight: "700", color: m.black, marginTop: 2 },
  tSub: { fontSize: 14.5, color: m.ink2, marginTop: 2 },
  tOpt: { fontSize: 17, fontWeight: "700", color: m.black, marginTop: 2, lineHeight: 22 },
  divider: { height: 1, backgroundColor: "#eef0f4", marginTop: 14, marginHorizontal: -18 },
  toast: {
    position: "absolute",
    left: 18,
    right: 18,
    top: -46,
    zIndex: 5,
    backgroundColor: "rgba(17,18,22,0.92)",
    borderRadius: 10,
    paddingVertical: 10,
    paddingHorizontal: 14,
    alignItems: "center",
  },
  toastText: { color: m.white, fontSize: 14, fontWeight: "600" },
  primary: {
    marginTop: 14,
    height: 54,
    borderRadius: radius.button,
    backgroundColor: m.black,
    alignItems: "center",
    justifyContent: "center",
  },
  primaryText: { color: m.white, fontSize: 17, fontWeight: "600" },
  secondary: {
    marginTop: 10,
    height: 54,
    borderRadius: radius.button,
    borderWidth: 1,
    borderColor: m.lineStrong,
    alignItems: "center",
    justifyContent: "center",
  },
  secondaryText: { color: m.black, fontSize: 17, fontWeight: "600" },
});
