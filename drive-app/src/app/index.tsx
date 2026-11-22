// Main route: the MILES-style home (src/miles/, concept replica) hosting the Rescue feature (src/rescue/).
// €5 badge on rescue cars -> offer in the car sheet -> reserve + walk -> drive to the value-map destination -> credit.
// Deep link fuelback://rescue/<id> (route src/app/rescue/[id].tsx) lands here as /?rescue=<id>. ?embed=1 is handled
// by useInsets (src/lib/embed). Booking/reservation buttons of the replica are inert.
import { useCallback, useEffect, useMemo, useState } from "react";
import { Modal, Platform, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { useLocalSearchParams, router } from "expo-router";
import { useInsets, EMBED } from "@/lib/embed";
import { haptic } from "@/lib/haptics";
import { locate, useLocationStore } from "@/lib/location";
import { PLACES } from "@/lib/config";
import {
  useFleet,
  useRescueFlow,
  RescuePanel,
  RescueBadge,
  rescueColors,
  REWARD_EUR,
  RESCUE_WALK_MAX,
  type FleetMeta,
  type Vehicle,
} from "@/rescue";
import { MilesHomeScreen } from "@/miles/MilesHomeScreen";
import { VehicleSheet } from "@/miles/components/VehicleSheet";
import { m, radius } from "@/miles/theme";

type PosKey = "demo" | "cic" | "gps";
type Pt = { lat: number; lon: number };

const badgeHtml = (sel: boolean) =>
  `<div style="display:flex;flex-direction:column;align-items:center;transform:scale(${sel ? 1.15 : 1})">` +
  `<div style="height:26px;min-width:42px;padding:0 9px;box-sizing:border-box;border-radius:13px;border:2px solid ${sel ? rescueColors.accent : "#fff"};` +
  `background:${sel ? "#fff" : rescueColors.accent};color:${sel ? rescueColors.accent : "#fff"};font:800 13px -apple-system,Helvetica Neue,Arial,sans-serif;` +
  `display:flex;align-items:center;justify-content:center;box-shadow:0 2px 5px rgba(0,0,0,.2)">€${REWARD_EUR}</div>` +
  `<div style="width:0;height:0;border-left:5px solid transparent;border-right:5px solid transparent;border-top:6px solid ${rescueColors.accent};margin-top:-1px"></div></div>`;

export default function Home() {
  const insets = useInsets();
  const { doc, from } = useFleet();
  const loc = useLocationStore();
  const params = useLocalSearchParams<{ rescue?: string; car?: string }>();

  const [posKey, setPosKey] = useState<PosKey>("demo");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [rescueOnly, setRescueOnly] = useState(false);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [focus, setFocus] = useState<{ pts: Pt[]; key: string } | null>(null);
  const fit = useCallback((pts: Pt[]) => setFocus({ pts, key: `${Date.now()}` }), []);

  const basePos = useMemo(() => {
    if (posKey === "gps" && loc.place.src === "gps") return { lat: loc.place.lat, lon: loc.place.lon, name: "Your location" };
    if (posKey === "cic") return { ...PLACES.cic, name: "CIC Berlin" };
    return doc.demoPosition;
  }, [posKey, loc.place, doc.demoPosition]);

  const flow = useRescueFlow(doc.vehicles, basePos);
  const idle = flow.stage === "idle";
  const selected = useMemo(() => flow.cars.find((c) => c.id === selectedId) ?? null, [flow.cars, selectedId]);

  const shownCars = useMemo(() => {
    if (!idle && flow.active) return flow.cars.filter((c) => c.id === flow.active!.id);
    return rescueOnly ? flow.cars.filter((c) => flow.rescueIds.has(c.id)) : flow.cars;
  }, [flow.cars, flow.active, flow.rescueIds, rescueOnly, idle]);

  // Open framed on you + the rescue cars near you (again when the server copy replaces the bundled one).
  useEffect(() => {
    if (idle && !selectedId) fit([basePos, ...flow.nearby.slice(0, 6)]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [from, posKey, loc.place]);

  // Camera follows the flow.
  useEffect(() => {
    const a = flow.active;
    if (flow.stage === "walking" && a) fit([basePos, a]);
    if (flow.stage === "driving" && a?.rescue.dest) fit([a, a.rescue.dest]);
    if (flow.stage === "done" && a?.rescue.dest) fit([a.rescue.dest]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flow.stage]);

  // Deep link: fuelback://rescue/<id> -> /?rescue=<id>; the search screen opens a car with /?car=<id>.
  useEffect(() => {
    const id = Number(params.rescue || params.car);
    if (!id || !idle) return;
    const v = flow.cars.find((c) => c.id === id);
    if (!v) return;
    setSelectedId(id);
    fit(params.rescue ? [basePos, v] : [v]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.rescue, params.car, flow.cars]);

  const select = (id: number | null) => {
    if (!idle) return;
    if (id == null) {
      setSelectedId(null);
      return;
    }
    haptic("select");
    setSelectedId(id);
    const v = flow.cars.find((c) => c.id === id);
    if (v) fit(flow.rescueIds.has(id) ? [basePos, v] : [v]);
  };

  const finish = () => {
    flow.finish();
    setSelectedId(null);
    fit([basePos, ...flow.nearby.filter((n) => n.id !== flow.active?.id).slice(0, 6)]);
    if (params.rescue) router.setParams({ rescue: undefined });
  };
  const flowForPanel = { ...flow, finish };

  const renderMarkerOverlay = useCallback(
    (v: Vehicle) => (flow.rescueIds.has(v.id) ? <RescueBadge amount={REWARD_EUR} selected={v.id === selectedId} /> : null),
    [flow.rescueIds, selectedId],
  );
  const webOverlayHtml = useCallback(
    (v: Vehicle) => (flow.rescueIds.has(v.id) ? badgeHtml(v.id === selectedId) : null),
    [flow.rescueIds, selectedId],
  );

  const sheetFor = (v: Vehicle | null) => {
    if (!v) return null;
    const isOffer = !!flow.offerFor(v);
    if (idle && !isOffer) return <VehicleSheet vehicle={v} bottomPad={insets.bottom} />;
    return (
      <VehicleSheet
        vehicle={v}
        bottomPad={insets.bottom}
        mode={idle ? "compact" : "head"}
        slot={<RescuePanel flow={flowForPanel} vehicle={v} />}
      />
    );
  };

  return (
    <View style={styles.screen}>
      <MilesHomeScreen
        vehicles={shownCars}
        me={flow.meNow}
        selectedId={selectedId}
        onSelectVehicle={select}
        renderMarkerOverlay={renderMarkerOverlay}
        webOverlayHtml={webOverlayHtml}
        overlayIds={flow.rescueIds}
        bottomSheetSlot={sheetFor}
        route={flow.route}
        dest={flow.dest ? { ...flow.dest } : null}
        focus={focus?.pts ?? null}
        focusKey={focus?.key ?? "init"}
        onLocate={() => fit([basePos])}
        onMenu={() => setAboutOpen(true)}
        onHelp={() => setAboutOpen(true)}
        searchHref="/miles/search"
        bottomBar={
          <Pressable
            style={[styles.rescuePill, rescueOnly && styles.rescuePillOn]}
            onPress={() => {
              haptic("select");
              const next = !rescueOnly;
              setRescueOnly(next);
              if (next && flow.nearby.length) fit([basePos, ...flow.nearby]);
            }}
            accessibilityLabel="Show rescue cars"
          >
            <View style={[styles.rescueBadge, rescueOnly && { backgroundColor: "#fff" }]}>
              <Text style={[styles.rescueBadgeText, rescueOnly && { color: rescueColors.accent }]}>€{REWARD_EUR}</Text>
            </View>
            <Text style={styles.rescueText}>
              {flow.nearby.length ? `Rescue · ${flow.nearby.length} near you` : "No rescues near you"}
            </Text>
          </Pressable>
        }
      />

      <About
        open={aboutOpen}
        onClose={() => setAboutOpen(false)}
        posKey={posKey}
        posName={basePos.name}
        onPos={(k) => {
          setAboutOpen(false);
          if (!idle) return;
          setSelectedId(null);
          setPosKey(k);
          if (k === "gps") void locate(true);
          const p = k === "cic" ? PLACES.cic : k === "demo" ? doc.demoPosition : null;
          if (p) fit([p]);
        }}
        meta={doc.meta}
        from={from}
        rescueCount={doc.vehicles.filter((v) => v.rescue).length}
        fleetCount={doc.vehicles.length}
      />
    </View>
  );
}

function About({
  open,
  onClose,
  posKey,
  posName,
  onPos,
  meta,
  from,
  rescueCount,
  fleetCount,
}: {
  open: boolean;
  onClose: () => void;
  posKey: PosKey;
  posName: string;
  onPos: (k: PosKey) => void;
  meta: FleetMeta;
  from: "server" | "bundled";
  rescueCount: number;
  fleetCount: number;
}) {
  const insets = useInsets();
  const opts = (
    [
      { k: "demo", label: "Demo position · Elsenstraße, Treptow" },
      { k: "cic", label: "CIC Berlin" },
      { k: "gps", label: Platform.OS === "web" ? "My location (browser GPS)" : "My location (GPS)" },
    ] as { k: PosKey; label: string }[]
  ).filter((o) => !(EMBED && o.k === "gps"));
  return (
    <Modal visible={open} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose}>
        <Pressable style={[styles.about, { paddingBottom: insets.bottom + 18 }]} onPress={() => {}}>
          <ScrollView contentContainerStyle={{ gap: 14 }}>
            <Text style={styles.aboutTitle}>Rescue — a feature concept for the MILES app</Text>
            <Text style={styles.aboutP}>
              Not the MILES app and not affiliated with MILES Mobility. A look-alike prototype built to show one feature:
              the 10% of cars TabPFN rates most likely to sit unrented 12 h+ get a €{REWARD_EUR} Rescue offer. A nearby customer moves
              the car to an area where it rents fast again. There's no login, booking or payment.
            </Text>
            <View style={styles.aboutBox}>
              <Row k="Vehicles" v={`${fleetCount} parked cars from the ${meta.source}, snapshot ${meta.snapshot}. Demo data, not live.`} />
              <Row k="Served" v={from === "server" ? "miles.bolls.dev/app/api/vehicles.json" : "bundled offline copy (server not reached)"} />
              <Row k="Rescue pins" v={`${rescueCount} cars: ${meta.model}; rule ${meta.rescueRule}. Offers only within a ${RESCUE_WALK_MAX}-min walk.`} />
              <Row k="Destination" v={`Value map: ${meta.valueMap}.`} />
              <Row k="97% still there" v="Policy figure: offers go only to cars predicted ≥95% still there on arrival. The per-car score isn't wired into this demo." />
            </View>
            <Text style={styles.aboutH}>Your position</Text>
            {opts.map((o) => (
              <Pressable key={o.k} style={[styles.posItem, posKey === o.k && styles.posItemOn]} onPress={() => onPos(o.k)}>
                <Text style={styles.posText}>{o.label}</Text>
                {posKey === o.k ? <Text style={styles.posNow}>{posName}</Text> : null}
              </Pressable>
            ))}
            <Pressable style={styles.closeBtn} onPress={onClose}>
              <Text style={styles.closeText}>Close</Text>
            </Pressable>
          </ScrollView>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <View style={{ gap: 2 }}>
      <Text style={styles.rowK}>{k}</Text>
      <Text style={styles.rowV}>{v}</Text>
    </View>
  );
}

const pillShadow =
  Platform.OS === "web"
    ? ({ boxShadow: "0 2px 10px rgba(0,0,0,0.18)" } as any)
    : { shadowColor: "#000", shadowOpacity: 0.18, shadowRadius: 8, shadowOffset: { width: 0, height: 2 }, elevation: 5 };

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: m.mapBg },
  rescuePill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    backgroundColor: m.navy,
    borderRadius: radius.pill,
    paddingLeft: 6,
    paddingRight: 18,
    height: 50,
    ...pillShadow,
  },
  rescuePillOn: { backgroundColor: rescueColors.accent },
  rescueBadge: {
    backgroundColor: rescueColors.accent,
    borderRadius: radius.pill,
    paddingHorizontal: 10,
    height: 38,
    minWidth: 38,
    alignItems: "center",
    justifyContent: "center",
  },
  rescueBadgeText: { color: "#fff", fontWeight: "800", fontSize: 15 },
  rescueText: { color: "#fff", fontWeight: "600", fontSize: 16 },
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.35)", justifyContent: "flex-end" },
  about: {
    backgroundColor: "#fff",
    borderTopLeftRadius: radius.sheet,
    borderTopRightRadius: radius.sheet,
    padding: 20,
    maxHeight: "88%",
  },
  aboutTitle: { fontSize: 22, fontWeight: "800", color: m.black, letterSpacing: -0.4 },
  aboutP: { fontSize: 15, color: m.ink2, lineHeight: 21 },
  aboutBox: { backgroundColor: m.card, borderRadius: radius.card, padding: 14, gap: 10 },
  aboutH: { fontSize: 13, fontWeight: "700", color: m.muted, letterSpacing: 0.6, textTransform: "uppercase" },
  rowK: { fontSize: 12, fontWeight: "700", color: m.muted, letterSpacing: 0.4, textTransform: "uppercase" },
  rowV: { fontSize: 14, color: m.black, lineHeight: 19 },
  posItem: { borderWidth: 1, borderColor: m.lineStrong, borderRadius: radius.card, padding: 14 },
  posItemOn: { borderColor: m.black, borderWidth: 2, padding: 13 },
  posText: { fontSize: 15.5, fontWeight: "600", color: m.black },
  posNow: { fontSize: 13, color: m.muted, marginTop: 2 },
  closeBtn: { minHeight: 54, borderRadius: radius.button, backgroundColor: m.black, alignItems: "center", justifyContent: "center" },
  closeText: { color: "#fff", fontWeight: "600", fontSize: 17 },
});
