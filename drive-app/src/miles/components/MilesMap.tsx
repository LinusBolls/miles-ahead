// Native MILES-style map: Apple Maps (react-native-maps, never Google on iOS), muted standard style,
// black "M" pins, black count clusters, optional per-car overlay slot (Rescue's €5 badge).
import { useEffect, useMemo, useRef, useState } from "react";
import { StyleSheet, View } from "react-native";
import MapView, { Marker, Polyline, type Region } from "react-native-maps";
import { cluster } from "../data";
import { CarPin, ClusterPin, DestPin, MeDot } from "./Pins";
import type { MilesMapProps } from "./mapTypes";

const MAX_MARKERS = 160;

export function MilesMap(p: MilesMapProps) {
  const ref = useRef<MapView>(null);
  const initial = useMemo<Region>(
    () => ({ latitude: p.center.lat, longitude: p.center.lon, latitudeDelta: 0.011, longitudeDelta: 0.011 }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const [region, setRegion] = useState<Region>(initial);

  useEffect(() => {
    if (p.recenterKey === undefined) return;
    ref.current?.animateToRegion(
      { latitude: p.center.lat, longitude: p.center.lon, latitudeDelta: 0.012, longitudeDelta: 0.012 },
      400,
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.recenterKey]);

  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (!ready || !p.focus || !p.focus.length) return;
    const coords = p.focus.map((c) => ({ latitude: c.lat, longitude: c.lon }));
    if (coords.length === 1) {
      ref.current?.animateToRegion({ ...coords[0], latitudeDelta: 0.01, longitudeDelta: 0.01 }, 450);
      return;
    }
    ref.current?.fitToCoordinates(coords, {
      edgePadding: { top: (p.topInset ?? 80) + 40, bottom: (p.bottomInset ?? 0) + 40, left: 50, right: 50 },
      animated: true,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.focusKey, ready]);

  useEffect(() => {
    if (p.focus) return; // the host drives the camera
    const v = p.vehicles.find((x) => x.id === p.selectedId);
    if (!v) return;
    // nudge the camera so the car sits above the bottom sheet
    const shift = region.latitudeDelta * ((p.bottomInset ?? 0) / 2 / 844);
    ref.current?.animateToRegion(
      { latitude: v.lat - shift, longitude: v.lon, latitudeDelta: region.latitudeDelta, longitudeDelta: region.longitudeDelta },
      350,
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.selectedId]);

  const { singles, clusters } = useMemo(() => {
    const la = region.latitudeDelta * 0.75, lo = region.longitudeDelta * 0.75;
    const inside = p.vehicles.filter(
      (c) => Math.abs(c.lat - region.latitude) < la && Math.abs(c.lon - region.longitude) < lo,
    );
    const keep = new Set<number>(p.overlayIds ?? []);
    if (p.selectedId != null) keep.add(p.selectedId);
    // cluster cell ≈ 1/9 of the screen width; no clustering when zoomed in close
    const cell = region.longitudeDelta < 0.006 ? 0 : region.longitudeDelta / 9;
    const res = cell ? cluster(inside, cell, keep) : { singles: inside, clusters: [] };
    if (res.singles.length > MAX_MARKERS) res.singles.length = MAX_MARKERS;
    return res;
  }, [p.vehicles, p.overlayIds, p.selectedId, region]);

  return (
    <View style={StyleSheet.absoluteFill}>
      <MapView
        ref={ref}
        style={StyleSheet.absoluteFill}
        initialRegion={initial}
        mapType="mutedStandard"
        onRegionChangeComplete={setRegion}
        onMapReady={() => setReady(true)}
        onPress={(e) => {
          if (e.nativeEvent.action !== "marker-press") p.onMapPress?.();
        }}
        showsUserLocation={false}
        showsMyLocationButton={false}
        showsCompass={false}
        showsPointsOfInterests={false}
        showsBuildings={false}
        toolbarEnabled={false}
        rotateEnabled={false}
        pitchEnabled={false}
      >
        {p.route && p.route.length > 1 ? (
          <Polyline
            coordinates={p.route.map((c) => ({ latitude: c.lat, longitude: c.lon }))}
            strokeColor="#000"
            strokeWidth={3}
            lineDashPattern={[2, 6]}
          />
        ) : null}
        {clusters.map((c) => (
          <Marker
            key={`c${c.key}-${c.ids.length}`}
            coordinate={{ latitude: c.lat, longitude: c.lon }}
            anchor={{ x: 0.5, y: 0.5 }}
            tracksViewChanges={false}
            onPress={() =>
              ref.current?.animateToRegion(
                {
                  latitude: c.lat,
                  longitude: c.lon,
                  latitudeDelta: region.latitudeDelta / 2.5,
                  longitudeDelta: region.longitudeDelta / 2.5,
                },
                350,
              )
            }
          >
            <ClusterPin count={c.ids.length} />
          </Marker>
        ))}
        {singles.map((v) => {
          const sel = v.id === p.selectedId;
          const overlay = p.renderMarkerOverlay?.(v) ?? null;
          return (
            <Marker
              key={`v${v.id}-${sel ? 1 : 0}-${overlay ? 1 : 0}`}
              coordinate={{ latitude: v.lat, longitude: v.lon }}
              anchor={{ x: 0.5, y: 1 }}
              onPress={() => p.onSelectVehicle(v.id)}
              tracksViewChanges={false}
              zIndex={sel ? 30 : overlay ? 20 : 10}
            >
              <View style={styles.pinCol}>
                {overlay}
                <CarPin selected={sel} />
              </View>
            </Marker>
          );
        })}
        {p.dest ? (
          <Marker
            key={`dest-${p.dest.name}`}
            coordinate={{ latitude: p.dest.lat, longitude: p.dest.lon }}
            anchor={{ x: 0.5, y: 0.9 }}
            tracksViewChanges={false}
            zIndex={35}
          >
            <DestPin name={p.dest.name} />
          </Marker>
        ) : null}
        {p.me ? (
          <Marker coordinate={{ latitude: p.me.lat, longitude: p.me.lon }} anchor={{ x: 0.5, y: 0.5 }} tracksViewChanges={false} zIndex={40}>
            <MeDot />
          </Marker>
        ) : null}
      </MapView>
    </View>
  );
}

const styles = StyleSheet.create({
  pinCol: { alignItems: "center" },
});
