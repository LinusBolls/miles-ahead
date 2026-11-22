// Searching for cars: "Fahrzeuge" list in the MILES app's layout (back arrow + title, address search field,
// vehicle-type chips, cards sorted by walking distance, floating "Filters" pill that opens a filter sheet).
// Search + filters work locally on the demo data; tapping a card opens that car on the home map.
import { useMemo, useState } from "react";
import { FlatList, Modal, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { useRouter } from "expo-router";
import { useInsets } from "@/lib/embed";
import { useFleet } from "@/lib/fleet";
import { m, radius, shadow } from "./theme";
import {
  CATEGORIES,
  displayModel,
  displayPlate,
  distLabel,
  inCategory,
  isVan,
  metres,
  rangeKm,
  type Category,
  type LatLon,
  type Vehicle,
} from "./data";
import { BackIcon, BoltIcon, CarArt, ChevronRight, CloseIcon, LocateIcon, PinIcon, RangeIcon, SearchIcon, SlidersIcon } from "./components/icons";
import { ConceptTag } from "./components/ConceptTag";

type Row = Vehicle & { dist: number };

/** Demo address suggestions near CIC Berlin (static, no geocoder is called). */
const PLACES = [
  { name: "Elsenstraße", sub: "Berlin-Treptow", lat: 52.4889, lon: 13.4547 },
  { name: "Ostkreuz", sub: "Berlin-Friedrichshain", lat: 52.5031, lon: 13.4692 },
  { name: "Hermannplatz", sub: "Berlin-Neukölln", lat: 52.4868, lon: 13.4245 },
  { name: "Warschauer Straße", sub: "Berlin-Friedrichshain", lat: 52.5058, lon: 13.4491 },
  { name: "Görlitzer Park", sub: "Berlin-Kreuzberg", lat: 52.4964, lon: 13.4381 },
  { name: "Sonnenallee", sub: "Berlin-Neukölln", lat: 52.4794, lon: 13.4468 },
  { name: "Treptower Park", sub: "Berlin-Treptow", lat: 52.4885, lon: 13.4713 },
];

export function MilesSearchScreen({ homeHref = "/" }: { homeHref?: string }) {
  const insets = useInsets();
  const router = useRouter();
  const fleet = useFleet();
  const me0: LatLon = (fleet.doc as any).demoPosition ?? fleet.doc.meta.center;

  const [query, setQuery] = useState("");
  const [focused, setFocused] = useState(false);
  const [origin, setOrigin] = useState<{ name: string } & LatLon>({ name: "Aktueller Standort", ...me0 });
  const [cat, setCat] = useState<Category>("all");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [minRange, setMinRange] = useState(0);
  const [evOnly, setEvOnly] = useState(false);

  const rows = useMemo<Row[]>(() => {
    return fleet.doc.vehicles
      .filter((v) => inCategory(v, cat) && rangeKm(v) >= minRange && (!evOnly || v.ev))
      .map((v) => ({ ...v, dist: metres(origin, v) }))
      .sort((a, b) => a.dist - b.dist)
      .slice(0, 40);
  }, [fleet.doc.vehicles, cat, minRange, evOnly, origin]);

  const suggestions = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return PLACES.slice(0, 4);
    return PLACES.filter((p) => p.name.toLowerCase().includes(q) || p.sub.toLowerCase().includes(q));
  }, [query]);

  const open = (id: number) => router.push(`${homeHref}?car=${id}` as any);
  const activeFilters = (minRange ? 1 : 0) + (evOnly ? 1 : 0);

  return (
    <View style={[styles.root, { paddingTop: insets.top }]}>
      <View style={styles.header}>
        <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace(homeHref as any))} hitSlop={12} style={styles.back}>
          <BackIcon />
        </Pressable>
        <Text style={styles.title}>Fahrzeuge</Text>
        <View style={styles.back} />
      </View>

      <View style={styles.searchWrap}>
        <View style={[styles.search, focused && styles.searchFocused]}>
          <SearchIcon size={19} color={m.muted} />
          <TextInput
            value={query}
            onChangeText={setQuery}
            onFocus={() => setFocused(true)}
            onBlur={() => setTimeout(() => setFocused(false), 150)}
            placeholder="Adresse oder Ort suchen"
            placeholderTextColor={m.faint}
            style={styles.searchInput}
            returnKeyType="search"
            autoCorrect={false}
          />
          {query ? (
            <Pressable onPress={() => setQuery("")} hitSlop={10}>
              <CloseIcon size={16} color={m.muted} />
            </Pressable>
          ) : null}
        </View>
        <Text style={styles.originLine}>
          Fahrzeuge in der Nähe von <Text style={styles.originStrong}>{origin.name}</Text>
        </Text>
      </View>

      {focused ? (
        <View style={styles.suggest}>
          <Pressable
            style={styles.sugRow}
            onPress={() => {
              setOrigin({ name: "Aktueller Standort", ...me0 });
              setQuery("");
              setFocused(false);
            }}
          >
            <View style={styles.sugIcon}>
              <LocateIcon size={16} />
            </View>
            <Text style={styles.sugName}>Aktueller Standort</Text>
          </Pressable>
          {suggestions.map((p) => (
            <Pressable
              key={p.name}
              style={styles.sugRow}
              onPress={() => {
                setOrigin(p);
                setQuery(p.name);
                setFocused(false);
              }}
            >
              <View style={styles.sugIcon}>
                <PinIcon size={17} />
              </View>
              <View>
                <Text style={styles.sugName}>{p.name}</Text>
                <Text style={styles.sugSub}>{p.sub}</Text>
              </View>
            </Pressable>
          ))}
        </View>
      ) : null}

      <View style={focused ? styles.hidden : undefined}>
        <FlatList
          horizontal
          data={CATEGORIES}
          keyExtractor={(c) => c.key}
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.chips}
          renderItem={({ item }) => {
            const on = item.key === cat;
            return (
              <Pressable onPress={() => setCat(item.key)} style={[styles.chip, on && styles.chipOn]}>
                <Text style={[styles.chipText, on && styles.chipTextOn]}>{item.label}</Text>
              </Pressable>
            );
          }}
        />
      </View>

      <FlatList
        style={focused ? styles.hidden : undefined}
        data={rows}
        keyExtractor={(v) => String(v.id)}
        contentContainerStyle={{ paddingHorizontal: 16, paddingTop: 4, paddingBottom: insets.bottom + 96, gap: 10 }}
        ListEmptyComponent={<Text style={styles.empty}>Keine Fahrzeuge für diese Filter.</Text>}
        renderItem={({ item: v }) => (
          <Pressable onPress={() => open(v.id)} style={({ pressed }) => [styles.card, pressed && { opacity: 0.8 }]}>
            <View style={styles.cardArt}>
              <CarArt width={128} van={isVan(v)} />
            </View>
            <View style={styles.cardBody}>
              <Text style={styles.cardPlate}>{displayPlate(v)}</Text>
              <View style={styles.modelRow}>
                <Text style={styles.cardModel}>{displayModel(v)}</Text>
                {v.ev ? <BoltIcon size={13} /> : null}
              </View>
              <View style={styles.rangeRow}>
                <RangeIcon size={15} />
                <Text style={styles.cardRange}>
                  {rangeKm(v)}km ({v.pct}%)
                </Text>
              </View>
              <View style={styles.distChip}>
                <Text style={styles.distText}>{distLabel(v.dist)}</Text>
                <LocateIcon size={13} color={m.blue} />
              </View>
            </View>
            <ChevronRight size={16} />
          </Pressable>
        )}
      />

      <Pressable
        onPress={() => setFiltersOpen(true)}
        style={({ pressed }) => [styles.filtersPill, shadow, { bottom: insets.bottom + 18 }, pressed && { opacity: 0.85 }]}
      >
        <Text style={styles.filtersText}>Filters{activeFilters ? ` (${activeFilters})` : ""}</Text>
        <SlidersIcon size={22} />
      </Pressable>

      <ConceptTag style={{ top: insets.top + 6, right: 12 }} />

      <Modal visible={filtersOpen} transparent animationType="slide" onRequestClose={() => setFiltersOpen(false)}>
        <Pressable style={styles.scrim} onPress={() => setFiltersOpen(false)} />
        <View style={[styles.filterSheet, { paddingBottom: insets.bottom + 16 }]}>
          <View style={styles.fsHead}>
            <Text style={styles.fsTitle}>Filters</Text>
            <Pressable onPress={() => setFiltersOpen(false)} hitSlop={12}>
              <CloseIcon />
            </Pressable>
          </View>
          <Text style={styles.fsSection}>Fahrzeugtyp</Text>
          <View style={styles.fsWrap}>
            {CATEGORIES.filter((c) => c.key !== "ev").map((c) => {
              const on = c.key === cat;
              return (
                <Pressable key={c.key} onPress={() => setCat(c.key)} style={[styles.chip, on && styles.chipOn]}>
                  <Text style={[styles.chipText, on && styles.chipTextOn]}>{c.label}</Text>
                </Pressable>
              );
            })}
          </View>
          <Text style={styles.fsSection}>Antrieb</Text>
          <View style={styles.fsWrap}>
            {[
              { on: !evOnly, label: "Alle", set: () => setEvOnly(false) },
              { on: evOnly, label: "Nur Elektro", set: () => setEvOnly(true) },
            ].map((o) => (
              <Pressable key={o.label} onPress={o.set} style={[styles.chip, o.on && styles.chipOn]}>
                <Text style={[styles.chipText, o.on && styles.chipTextOn]}>{o.label}</Text>
              </Pressable>
            ))}
          </View>
          <Text style={styles.fsSection}>Mindestreichweite</Text>
          <View style={styles.fsWrap}>
            {[0, 100, 200, 300].map((r) => {
              const on = r === minRange;
              return (
                <Pressable key={r} onPress={() => setMinRange(r)} style={[styles.chip, on && styles.chipOn]}>
                  <Text style={[styles.chipText, on && styles.chipTextOn]}>{r ? `${r}+ km` : "Egal"}</Text>
                </Pressable>
              );
            })}
          </View>
          <Pressable style={styles.fsApply} onPress={() => setFiltersOpen(false)}>
            <Text style={styles.fsApplyText}>{rows.length === 40 ? "40+" : rows.length} Fahrzeuge anzeigen</Text>
          </Pressable>
          <Pressable
            style={styles.fsReset}
            onPress={() => {
              setCat("all");
              setEvOnly(false);
              setMinRange(0);
            }}
          >
            <Text style={styles.fsResetText}>Zurücksetzen</Text>
          </Pressable>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: m.white },
  hidden: { display: "none" },
  header: { height: 56, flexDirection: "row", alignItems: "center", paddingHorizontal: 16 },
  back: { width: 40 },
  title: { flex: 1, textAlign: "center", fontSize: 18, fontWeight: "600", color: m.black },
  searchWrap: { paddingHorizontal: 16, paddingBottom: 6 },
  search: {
    height: 48,
    borderRadius: radius.button,
    borderWidth: 1,
    borderColor: m.lineStrong,
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 13,
    gap: 10,
  },
  searchFocused: { borderColor: m.black, borderWidth: 1.5 },
  searchInput: { flex: 1, fontSize: 16, color: m.black, height: 46, outlineStyle: "none" } as any,
  originLine: { fontSize: 13.5, color: m.muted, marginTop: 8 },
  originStrong: { color: m.black, fontWeight: "600" },
  suggest: { flex: 1, borderTopWidth: 1, borderTopColor: "#eef0f4", marginTop: 6 },
  sugRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingHorizontal: 16,
    paddingVertical: 11,
    backgroundColor: m.white,
    borderBottomWidth: 1,
    borderBottomColor: "#eef0f4",
  },
  sugIcon: { width: 32, height: 32, borderRadius: 16, backgroundColor: m.card, alignItems: "center", justifyContent: "center" },
  sugName: { fontSize: 15.5, color: m.black, fontWeight: "500" },
  sugSub: { fontSize: 13, color: m.muted, marginTop: 1 },
  chips: { paddingHorizontal: 16, paddingVertical: 10, gap: 8 },
  chip: {
    height: 40,
    paddingHorizontal: 18,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: m.lineStrong,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: m.white,
  },
  chipOn: { borderWidth: 2, borderColor: m.black, paddingHorizontal: 17 },
  chipText: { fontSize: 15, color: m.black },
  chipTextOn: { fontWeight: "600" },
  card: {
    backgroundColor: m.card,
    borderRadius: radius.card,
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: 12,
    paddingLeft: 12,
    paddingRight: 16,
    minHeight: 132,
  },
  cardArt: { width: 136, alignItems: "center" },
  cardBody: { flex: 1, paddingLeft: 14, gap: 4 },
  cardPlate: { fontSize: 18, fontWeight: "600", color: m.black },
  modelRow: { flexDirection: "row", alignItems: "center", gap: 5 },
  cardModel: { fontSize: 15.5, color: m.ink2 },
  rangeRow: { flexDirection: "row", alignItems: "center", gap: 5 },
  cardRange: { fontSize: 15.5, color: m.ink2 },
  distChip: {
    alignSelf: "flex-start",
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: m.blueChipBg,
    borderRadius: radius.pill,
    paddingHorizontal: 9,
    paddingVertical: 3,
    marginTop: 2,
  },
  distText: { color: m.blue, fontWeight: "600", fontSize: 15 },
  empty: { textAlign: "center", color: m.muted, marginTop: 40, fontSize: 15 },
  filtersPill: {
    position: "absolute",
    alignSelf: "center",
    height: 50,
    paddingHorizontal: 26,
    borderRadius: radius.pill,
    backgroundColor: m.navy,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
  },
  filtersText: { color: m.white, fontSize: 17, fontWeight: "600" },
  scrim: { flex: 1, backgroundColor: "rgba(0,0,0,0.35)" },
  filterSheet: {
    backgroundColor: m.white,
    borderTopLeftRadius: radius.sheet,
    borderTopRightRadius: radius.sheet,
    paddingHorizontal: 18,
    paddingTop: 18,
  },
  fsHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 6 },
  fsTitle: { fontSize: 20, fontWeight: "700", color: m.black },
  fsSection: { fontSize: 16, fontWeight: "600", color: m.black, marginTop: 16, marginBottom: 10 },
  fsWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  fsApply: {
    marginTop: 26,
    height: 56,
    borderRadius: radius.button,
    backgroundColor: m.black,
    alignItems: "center",
    justifyContent: "center",
  },
  fsApplyText: { color: m.white, fontSize: 17, fontWeight: "600" },
  fsReset: { height: 48, alignItems: "center", justifyContent: "center", marginTop: 4 },
  fsResetText: { color: m.blue, fontSize: 16, fontWeight: "600" },
});

