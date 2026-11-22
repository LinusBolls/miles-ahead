// Home: the map-first screen of the MILES app (concept replica for the Rescue pitch).
// Map fills the screen; black menu button top-left, "Hilfe" pill top-right, round search + locate buttons
// bottom-right; tapping a pin opens the vehicle sheet. Menu/Hilfe/booking buttons are inert.
//
// Extension points for Rescue: `renderMarkerOverlay` / `webOverlayHtml` / `overlayIds` go straight to the map,
// `sheetSlot(vehicle)` renders inside the vehicle sheet, `bottomSheetSlot` replaces the sheet entirely.
import { useMemo, useState, type ReactNode } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { useRouter } from "expo-router";
import { useInsets } from "@/lib/embed";
import { useFleet } from "@/lib/fleet";
import { m } from "./theme";
import type { LatLon, Vehicle } from "./data";
import { MilesMap } from "./components/MilesMap";
import type { MilesMapProps } from "./components/mapTypes";
import { HelpPill, MapControlsColumn, MenuButton, RoundButton } from "./components/MapChrome";
import { VehicleSheet } from "./components/VehicleSheet";
import { ConceptTag } from "./components/ConceptTag";
import { ChevronUp } from "./components/icons";

export type MilesHomeProps = {
  vehicles?: Vehicle[];
  me?: LatLon;
  selectedId?: number | null;
  onSelectVehicle?: (id: number | null) => void;
  renderMarkerOverlay?: MilesMapProps["renderMarkerOverlay"];
  webOverlayHtml?: MilesMapProps["webOverlayHtml"];
  overlayIds?: Set<number>;
  sheetSlot?: (v: Vehicle) => ReactNode;
  /** When set, replaces the default vehicle sheet (e.g. Rescue's own sheet). */
  bottomSheetSlot?: (v: Vehicle | null) => ReactNode;
  searchHref?: string;
  /** Rescue flow drawing + camera control (see MilesMapProps). */
  route?: MilesMapProps["route"];
  dest?: MilesMapProps["dest"];
  focus?: MilesMapProps["focus"];
  focusKey?: string;
  /** Called by the round "locate" button instead of the built-in recentre. */
  onLocate?: () => void;
  onMenu?: () => void;
  onHelp?: () => void;
  /** Extra floating control at the bottom-left while no sheet is open (e.g. Rescue's entry pill). */
  bottomBar?: ReactNode;
};

export function MilesHomeScreen(props: MilesHomeProps) {
  const insets = useInsets();
  const [sheetH, setSheetH] = useState(0);
  const router = useRouter();
  const fleet = useFleet();
  const vehicles = props.vehicles ?? fleet.doc.vehicles;
  const me: LatLon = props.me ?? (fleet.doc as any).demoPosition ?? fleet.doc.meta.center;

  const [ownSel, setOwnSel] = useState<number | null>(null);
  const selectedId = props.selectedId !== undefined ? props.selectedId : ownSel;
  const select = (id: number | null) => (props.onSelectVehicle ? props.onSelectVehicle(id) : setOwnSel(id));
  const selected = useMemo(() => vehicles.find((v) => v.id === selectedId) ?? null, [vehicles, selectedId]);
  const [recenter, setRecenter] = useState<number | undefined>(undefined);

  const sheet = props.bottomSheetSlot
    ? props.bottomSheetSlot(selected)
    : selected
      ? <VehicleSheet vehicle={selected} bottomPad={insets.bottom} slot={props.sheetSlot?.(selected)} />
      : null;

  return (
    <View style={styles.root}>
      <MilesMap
        vehicles={vehicles}
        selectedId={selectedId}
        onSelectVehicle={(id) => select(id)}
        onMapPress={() => select(null)}
        center={me}
        me={me}
        renderMarkerOverlay={props.renderMarkerOverlay}
        webOverlayHtml={props.webOverlayHtml}
        overlayIds={props.overlayIds}
        recenterKey={recenter}
        bottomInset={sheet ? sheetH : 90}
        topInset={insets.top + 110}
        route={props.route}
        dest={props.dest}
        focus={props.focus}
        focusKey={props.focusKey}
      />

      <View pointerEvents="box-none" style={[styles.top, { top: insets.top + 10 }]}>
        <MenuButton onPress={props.onMenu} />
        <HelpPill onPress={props.onHelp} />
      </View>

      <ConceptTag style={{ top: insets.top + 74, left: 16 }} />

      {!sheet ? (
        <View pointerEvents="box-none" style={[styles.controls, { bottom: insets.bottom + 28 }]}>
          <MapControlsColumn>
            <RoundButton kind="search" onPress={() => router.push((props.searchHref ?? "/miles/search") as any)} />
            <RoundButton kind="locate" onPress={props.onLocate ?? (() => setRecenter((n) => (n ?? 0) + 1))} />
          </MapControlsColumn>
        </View>
      ) : null}

      {!sheet && props.bottomBar ? (
        <View pointerEvents="box-none" style={[styles.bottomBar, { bottom: insets.bottom + 28 }]}>
          {props.bottomBar}
        </View>
      ) : null}

      {sheet ? (
        <View pointerEvents="box-none" style={styles.sheetWrap} onLayout={(e) => setSheetH(e.nativeEvent.layout.height)}>
          <Pressable style={styles.grabber} onPress={() => select(null)} accessibilityLabel="Schließen">
            <ChevronUp size={36} />
          </Pressable>
          {sheet}
        </View>
      ) : null}

      <View pointerEvents="none" style={[styles.dataTag, { top: insets.top + 74 }]}>
        <Text style={styles.dataTagText}>Demo-Daten · Juni 2024</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: m.mapBg, overflow: "hidden" },
  top: {
    position: "absolute",
    left: 16,
    right: 16,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  controls: { position: "absolute", right: 16 },
  bottomBar: { position: "absolute", left: 16 },
  sheetWrap: { position: "absolute", left: 0, right: 0, bottom: 0, zIndex: 10 },
  grabber: { alignSelf: "center", paddingHorizontal: 30, paddingVertical: 8 },
  dataTag: {
    position: "absolute",
    right: 16,
    backgroundColor: "rgba(255,255,255,0.85)",
    paddingHorizontal: 7,
    paddingVertical: 2.5,
    borderRadius: 5,
  },
  dataTagText: { fontSize: 10, color: m.muted, fontWeight: "600" },
});
