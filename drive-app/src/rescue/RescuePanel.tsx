// Rescue content for a host's bottom-sheet slot. Content only: the host draws the sheet chrome.
//   <RescuePanel flow={flow} vehicle={selectedVehicle} />
// renders the offer card for a rescue car (exact copy: "€5 · 4 min walk · 97% still there · money back if gone"),
// then the walk / drive / credit steps once accepted. Returns null for a car without an offer while idle.
import { useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { km } from "@/lib/format";
import { driveMinutes, HOLD_MIN, hours, offerLine, ROAD_FACTOR, TYPICAL_P } from "./logic";
import { rescueColors as c } from "./theme";
import type { RescueFlow } from "./useRescueFlow";
import type { ScoredRescue, Vehicle } from "./types";

export function RescuePanel({ flow, vehicle }: { flow: RescueFlow; vehicle: Vehicle | null }) {
  if (flow.stage === "walking" && flow.active)
    return <WalkingPanel o={flow.active} startedAt={flow.startedAt} onArrived={flow.arrived} onCancel={flow.cancel} />;
  if (flow.stage === "driving" && flow.active) return <DrivingPanel o={flow.active} onParked={flow.parked} />;
  if (flow.stage === "done" && flow.active) return <DonePanel o={flow.active} onDone={flow.finish} />;
  const offer = flow.offerFor(vehicle);
  return offer ? <RescueOfferCard o={offer} onRescue={() => flow.accept(offer)} /> : null;
}

function Btn({ label, onPress, kind = "primary" }: { label: string; onPress: () => void; kind?: "primary" | "text" }) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      style={({ pressed }) => [s.btn, kind === "primary" ? s.btnPrimary : s.btnText, pressed && { opacity: 0.8 }]}
    >
      <Text style={[s.btnLabel, { color: kind === "primary" ? "#fff" : c.ink }]}>{label}</Text>
    </Pressable>
  );
}

/** The offer: tag, the exact offer line, why (TabPFN) and where to (value map), one button. */
export function RescueOfferCard({ o, onRescue }: { o: ScoredRescue; onRescue: () => void }) {
  const d = o.rescue.dest;
  return (
    <View style={s.col}>
      <View style={s.box}>
        <View style={s.tag}>
          <Text style={s.tagText}>RESCUE</Text>
        </View>
        <Text style={s.offer}>{offerLine(o)}</Text>
        <Text style={s.why}>
          High risk of sitting unrented 12 h+ where it is:{" "}
          <Text style={s.b}>{Math.round(o.rescue.p * 100)}%</Text> <Text style={s.dim}>(TabPFN; typical car {TYPICAL_P}%)</Text>
        </Text>
        {d ? (
          <Text style={s.why}>
            Park it at <Text style={s.b}>{d.name}</Text>, {km(d.m)} away: cars there are rented again in ~{hours(d.waitH)}{" "}
            <Text style={s.dim}>(typical, June evenings)</Text>
          </Text>
        ) : null}
      </View>
      <Btn label="Rescue this car" onPress={onRescue} />
    </View>
  );
}

function useTicker(ms = 1000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

const mmss = (sec: number) => {
  const v = Math.max(0, Math.round(sec));
  return `${Math.floor(v / 60)}:${String(v % 60).padStart(2, "0")}`;
};

function StageHead({ step, o }: { step: string; o: ScoredRescue }) {
  return (
    <View style={s.stageRow}>
      <Text style={s.stageK}>{step}</Text>
      <Text style={s.stageK}>€{o.credit}</Text>
    </View>
  );
}

/** Reserved: walk to the car. The hold timer is real (15 min); arriving is a tap in this demo. */
export function WalkingPanel({
  o,
  startedAt,
  onArrived,
  onCancel,
}: {
  o: ScoredRescue;
  startedAt: number;
  onArrived: () => void;
  onCancel: () => void;
}) {
  const now = useTicker();
  const elapsed = (now - startedAt) / 1000;
  return (
    <View style={s.col}>
      <StageHead step="RESCUE · STEP 1 OF 2" o={o} />
      <View style={{ gap: 2 }}>
        <Text style={s.title}>Walk to the {o.model}</Text>
        <Text style={s.sub}>
          {o.plate} · {km(o.walkM)}
        </Text>
      </View>
      <View style={s.timers}>
        <View style={s.timer}>
          <Text style={s.timerV}>{mmss(o.walkMin * 60 - elapsed)}</Text>
          <Text style={s.timerK}>walk left</Text>
        </View>
        <View style={s.timer}>
          <Text style={s.timerV}>{mmss(HOLD_MIN * 60 - elapsed)}</Text>
          <Text style={s.timerK}>reserved for you</Text>
        </View>
      </View>
      <Text style={s.fine}>Money back if gone: if it's been taken when you get there, the €{o.credit} is yours anyway.</Text>
      <View style={{ gap: 4 }}>
        <Btn label="I'm at the car" onPress={onArrived} />
        <Btn label="Cancel rescue" kind="text" onPress={onCancel} />
      </View>
    </View>
  );
}

/** Driving the car to the value-map destination. */
export function DrivingPanel({ o, onParked }: { o: ScoredRescue; onParked: () => void }) {
  const d = o.rescue.dest!;
  return (
    <View style={s.col}>
      <StageHead step="RESCUE · STEP 2 OF 2" o={o} />
      <View style={{ gap: 2 }}>
        <Text style={s.title}>Drive it to {d.name}</Text>
        <Text style={s.sub}>
          {km(d.m * ROAD_FACTOR)} · ~{driveMinutes(d.m)} min · park legally near the pin
        </Text>
      </View>
      <View style={s.compare}>
        <View style={s.compareCol}>
          <Text style={s.compareV}>~{hours(d.waitH)}</Text>
          <Text style={s.compareK}>until it's rented again at {d.name} (typical)</Text>
        </View>
        <View style={s.divider} />
        <View style={s.compareCol}>
          <Text style={[s.compareV, { color: c.ink3 }]}>{Math.round(o.rescue.p * 100)}%</Text>
          <Text style={s.compareK}>chance it sat 12 h+ unrented where it was (TabPFN)</Text>
        </View>
      </View>
      <Btn label="I've parked here" onPress={onParked} />
    </View>
  );
}

export function DonePanel({ o, onDone }: { o: ScoredRescue; onDone: () => void }) {
  return (
    <View style={s.col}>
      <View style={{ alignItems: "center", gap: 8, paddingVertical: 4 }}>
        <View style={s.check}>
          <Text style={s.checkMark}>✓</Text>
        </View>
        <Text style={s.doneTitle}>€{o.credit} credit added</Text>
        <Text style={[s.sub, { textAlign: "center" }]}>
          The {o.model} is now at {o.rescue.dest?.name}, where it'll be rented again soon. The credit applies to your next
          MILES ride.
        </Text>
      </View>
      <Btn label="Done" onPress={onDone} />
    </View>
  );
}

const s = StyleSheet.create({
  col: { gap: 14 },
  box: { backgroundColor: c.accentSoft, borderRadius: 14, padding: 14, gap: 8 },
  tag: { alignSelf: "flex-start", backgroundColor: c.accent, borderRadius: 6, paddingHorizontal: 7, paddingVertical: 2 },
  tagText: { color: "#fff", fontSize: 11, fontWeight: "800", letterSpacing: 0.8 },
  offer: { fontSize: 18, fontWeight: "800", color: c.ink, letterSpacing: -0.3, lineHeight: 23 },
  why: { fontSize: 14, color: c.ink2, lineHeight: 19 },
  b: { color: c.ink, fontWeight: "700" },
  dim: { color: c.ink3 },
  btn: { minHeight: 52, borderRadius: 12, alignItems: "center", justifyContent: "center", paddingHorizontal: 16 },
  btnPrimary: { backgroundColor: c.ink },
  btnText: { minHeight: 40 },
  btnLabel: { fontSize: 17, fontWeight: "700" },
  fine: { fontSize: 12.5, color: c.ink3, textAlign: "center", lineHeight: 17 },
  stageRow: { flexDirection: "row", justifyContent: "space-between" },
  stageK: { fontSize: 12, fontWeight: "800", color: c.accent, letterSpacing: 0.8 },
  title: { fontSize: 24, fontWeight: "900", color: c.ink, letterSpacing: -0.6 },
  sub: { fontSize: 15, color: c.ink2, lineHeight: 20 },
  timers: { flexDirection: "row", gap: 10 },
  timer: { flex: 1, backgroundColor: c.chip, borderRadius: 14, padding: 12 },
  timerV: { fontSize: 26, fontWeight: "800", color: c.ink, fontVariant: ["tabular-nums"] },
  timerK: { fontSize: 13, color: c.ink2 },
  compare: { flexDirection: "row", backgroundColor: c.accentSoft, borderRadius: 14, padding: 14, gap: 12 },
  compareCol: { flex: 1, gap: 2 },
  divider: { width: 1, backgroundColor: "rgba(31,111,235,0.25)" },
  compareV: { fontSize: 26, fontWeight: "900", color: c.accent, letterSpacing: -0.5 },
  compareK: { fontSize: 13, color: c.ink2, lineHeight: 17 },
  check: { width: 60, height: 60, borderRadius: 30, backgroundColor: c.accent, alignItems: "center", justifyContent: "center" },
  checkMark: { color: "#fff", fontSize: 30, fontWeight: "800", marginTop: -2 },
  doneTitle: { fontSize: 28, fontWeight: "900", color: c.ink, letterSpacing: -0.6 },
});
