// Formatting helpers, ported verbatim from the /drive web app so the numbers read identically.

export const eur = (v: number, d = 2): string =>
  (v < 0 ? "−" : "") + "€" + Math.abs(v).toFixed(d).replace(/\.00$/, "");

export const km = (m: number): string =>
  m < 950 ? `${Math.round(m / 50) * 50} m` : `${(m / 1000).toFixed(1)} km`;

export const mins = (m: number): number => Math.max(1, Math.round(m));

/** "a 7-min" / "an 8-min" (grammar matches the web). */
export const aMin = (m: number): string => {
  const n = mins(m);
  const an = n === 8 || n === 11 || n === 18 || (n >= 80 && n < 90);
  return `${an ? "an" : "a"} ${n}-min`;
};

export const ago = (s: number): string =>
  s < 60
    ? `${Math.max(0, Math.round(s))} s ago`
    : s < 3600
      ? `${Math.round(s / 60)} min ago`
      : `${Math.round(s / 3600)} h ago`;

export const colorName = (c: string | null | undefined): string =>
  c ? c.toLowerCase().replace("grey", "gray") : "";

// Great-circle distance in metres.
export const haversine = (a: number, b: number, c: number, d: number): number => {
  const p = Math.PI / 180;
  const x =
    Math.sin((c - a) * p / 2) ** 2 +
    Math.cos(a * p) * Math.cos(c * p) * Math.sin((d - b) * p / 2) ** 2;
  return 12742000 * Math.asin(Math.sqrt(x));
};
