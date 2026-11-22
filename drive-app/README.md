# drive-app: the rider-side concept (PWA + iOS)

A concept of how the rescue feature could look inside a car-sharing app: a map that badges only the cars predicted to
strand, with a €5 offer to move one a short distance to an area where it will be rented sooner. Expo SDK 58 +
expo-router; the same source builds the web PWA served at <https://miles.bolls.dev/app/> and an iOS build.

**Concept, demo data, unofficial.** Every screen carries a "Concept · demo" tag. The MILES-style screens in
`src/miles/` are a hand-drawn replica (icons drawn in SVG, system fonts; no MILES image or font files are bundled), and
their booking buttons do nothing. Not affiliated with or endorsed by MILES Mobility.

## What is real and what is not

- **Data:** one snapshot (Tue 18 Jun 2024, 21:00 Berlin) of the June 2024 replay, bundled as `src/data/vehicles.json`.
  Positions, models, masked plates and fuel levels are real replay rows. Nothing is live.
- **Which cars get a badge:** TabPFN P(idle > 12 h after the ride end), **precomputed** out-of-sample (June 17-22 ride
  ends scored with the June 3-16 context) by `miles-ops/backend/build_tabpfn.py`; badge if p >= 0.4556 (the top 10% of
  replay ride ends) and the car has been parked < 12 h. The app itself calls no model.
- **Where to send the car:** the nearby 1 km cell with the lowest *observed* median idle time for weekday-evening ride
  ends (June 3-22). Observed, not the TabPFN value map.
- **"97% still there":** a fixed policy figure (`src/rescue/logic.ts`), not a per-car still-there score.
- **Credit, reservation and payout:** simulated; nothing is booked.

`scripts/build_rescue_data.py` regenerates `src/data/vehicles.json` from `miles-ops/backend/geo/replay_berlin_2024-06.parquet`
(not committed; rebuilt by `miles-ops/backend/build_replay.py` + `build_tabpfn.py`).

## Layout

- `src/app/` - routes (`index.tsx` = replica home hosting the rescue feature, `rescue/[id].tsx` deep link, `miles/`).
- `src/rescue/` - the rescue feature: data contract (`types.ts`), offer logic, panel, badge, flow state.
- `src/miles/` - the replica screens (map, search, vehicle sheet).
- `src/lib/` - location, notifications, background check, OTA, storage, formatting.
- `modules/rescue-engagement/`, `targets/widget/` - native iOS module + WidgetKit / Live Activity targets.
- `public/` - PWA shell, manifest, service worker, vendored MapLibre (BSD-3, licence alongside).

## Build

```bash
pnpm install
npx tsc --noEmit                                   # typecheck
EXPO_WEB_BASE_URL=/app npx expo export --platform web --output-dir dist-web   # web PWA
scripts/build_web                                  # same, then stages into ../miles-atlas/static/app/
eas build -p ios --profile preview                 # iOS (EAS cloud; needs your own Apple credentials)
```

iOS signing credentials are not in this repo: put your own App Store Connect values into `eas.json` (placeholders)
and your own `asc-key.p8` (gitignored) if you want to build and submit.
