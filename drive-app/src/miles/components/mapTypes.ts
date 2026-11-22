import type { ReactNode } from "react";
import type { LatLon, Vehicle } from "../data";

/**
 * MILES-style map. Native: Apple Maps (react-native-maps, muted standard). Web: MapLibre (MilesMap.web.tsx).
 * Extension points for Rescue: `renderMarkerOverlay` (e.g. a "€5" badge above a pin; return null for none)
 * and `overlayIds` (cars that should never be clustered, e.g. rescue candidates).
 */
export type MilesMapProps = {
  vehicles: Vehicle[];
  selectedId: number | null;
  onSelectVehicle: (id: number) => void;
  onMapPress?: () => void;
  center: LatLon;
  /** "You are here" dot. */
  me?: LatLon | null;
  /**
   * Optional overlay drawn above a car's pin. Native: any ReactNode. Web: the node must be
   * a simple string/number (it is rendered as a badge label) OR you pass `webOverlayHtml`.
   */
  renderMarkerOverlay?: (v: Vehicle) => ReactNode | null;
  /** Web only: HTML string for the overlay (MapLibre DOM marker). Falls back to text of renderMarkerOverlay. */
  webOverlayHtml?: (v: Vehicle) => string | null;
  /** Cars that are always drawn individually (never clustered). */
  overlayIds?: Set<number>;
  /** Bump to recentre on `center` (the round "locate" button). */
  recenterKey?: number;
  /** Space covered by sheets at the bottom, so the selected car is centred above them. */
  bottomInset?: number;
  /** Space covered by the top controls (used when fitting `focus`). */
  topInset?: number;
  /** Dashed route (Rescue: walk to the car, then drive to the destination). */
  route?: LatLon[] | null;
  /** Destination ring with a label (Rescue: value-map destination). */
  dest?: (LatLon & { name: string }) | null;
  /** Fit the camera to these points whenever `focusKey` changes. */
  focus?: LatLon[] | null;
  focusKey?: string;
};
