// The shape of https://miles.bolls.dev/drive/api/cars (see miles-drive/app.py).

export type Station = {
  lat: number;
  lon: number;
  name: string;
  op: string;
  kw: number | null;
  partner: string | null; // "likely" | null
  m: number; // metres from the car (straight line, already road-factored server side? no — raw; drive.js multiplies by road_factor)
};

export type Kind = "fuel" | "ev" | "deal";

export type Car = {
  id: number;
  lat: number;
  lon: number;
  pct: number;
  range: number;
  model: string;
  size: string;
  color: string;
  plate: string; // masked, e.g. "••59"
  ev: boolean;
  kinds: Kind[];
  km_price: number;
  unlock: number;
  deal: string | null;
  bonus: number | null;
  st?: Station | null;
  km_to_threshold?: number;
  since: number;
};

export type Rules = {
  credit_ev: number;
  credit_fuel: number;
  ev_max: number;
  fuel_max: number;
  road_factor: number;
  km_price: Record<string, number>;
  unlock: Record<string, number>;
};

export type FleetEvent = {
  t: number;
  type: "new" | "gone";
  id: number;
  model: string;
  pct: number;
  ev: boolean;
};

export type Snapshot = {
  ok: boolean;
  city: string;
  generated_at: string;
  data_at: string | null;
  fleet: { deployed: number; electric: number };
  rules: Rules;
  done_today?: { refuels: number; charges: number; credits_eur: number; last: string | null };
  did_count: number;
  events: FleetEvent[];
  cars: Car[];
};

/** A car after scoring from the user's current spot (port of drive.js `evaluate`). */
export type Scored = {
  c: Car;
  walkM: number;
  walkMin: number;
  kind: "fuel" | "ev";
  credit: number;
  driveKm: number;
  cost: number;
  net: number;
  stM: number | null;
  score: number;
};

export type Place = { lat: number; lon: number; name: string; src: "gps" | "cic" | "alex" | "pin" };
