// Generic UI icons, drawn from scratch in SVG (no MILES image files are used).
import Svg, { Circle, Path, Rect } from "react-native-svg";
import { m } from "../theme";

type P = { size?: number; color?: string };

export const MenuIcon = ({ size = 24, color = m.white }: P) => (
  <Svg width={size} height={size} viewBox="0 0 24 24">
    <Path d="M3.5 6.5h17M3.5 12h17M3.5 17.5h17" stroke={color} strokeWidth={2.4} strokeLinecap="round" />
  </Svg>
);

export const HelpIcon = ({ size = 22, color = m.black }: P) => (
  <Svg width={size} height={size} viewBox="0 0 24 24">
    <Circle cx={12} cy={12} r={10.5} stroke={color} strokeWidth={1.4} fill="none" />
    <Path
      d="M9.4 9.3a2.7 2.7 0 0 1 5.3.6c0 1.8-2.5 2.2-2.5 3.9"
      stroke={color}
      strokeWidth={1.9}
      strokeLinecap="round"
      fill="none"
    />
    <Circle cx={12.2} cy={16.9} r={1.15} fill={color} />
  </Svg>
);

export const SearchIcon = ({ size = 24, color = m.black }: P) => (
  <Svg width={size} height={size} viewBox="0 0 24 24">
    <Circle cx={10.5} cy={10.5} r={6.2} stroke={color} strokeWidth={2.6} fill="none" />
    <Path d="M15.2 15.2l5 5" stroke={color} strokeWidth={2.8} strokeLinecap="round" />
  </Svg>
);

/** Filled navigation arrow ("locate me"). */
export const LocateIcon = ({ size = 22, color = m.locate }: P) => (
  <Svg width={size} height={size} viewBox="0 0 24 24">
    <Path d="M20.5 3.5L3.6 10.3l7.1 2.9 2.9 7.3z" fill={color} />
  </Svg>
);

export const BackIcon = ({ size = 26, color = m.black }: P) => (
  <Svg width={size} height={size} viewBox="0 0 26 26">
    <Path d="M23 13H4M11 5.5L3.5 13l7.5 7.5" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" fill="none" />
  </Svg>
);

export const ChevronRight = ({ size = 16, color = m.black }: P) => (
  <Svg width={size} height={size} viewBox="0 0 16 16">
    <Path d="M6 3.5L10.5 8 6 12.5" stroke={color} strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round" fill="none" />
  </Svg>
);

export const ChevronUp = ({ size = 34, color = m.white }: P) => (
  <Svg width={size} height={size * 0.4} viewBox="0 0 34 14">
    <Path d="M3 11.5L17 3.5l14 8" stroke={color} strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" fill="none" />
  </Svg>
);

export const CloseIcon = ({ size = 20, color = m.black }: P) => (
  <Svg width={size} height={size} viewBox="0 0 20 20">
    <Path d="M4.5 4.5l11 11M15.5 4.5l-11 11" stroke={color} strokeWidth={2} strokeLinecap="round" />
  </Svg>
);

/** Small "fuel gauge" glyph used next to the range (a phone-like battery slab). */
export const RangeIcon = ({ size = 16, color = m.black }: P) => (
  <Svg width={size} height={size} viewBox="0 0 16 16">
    <Rect x={3.5} y={1.5} width={9} height={13} rx={2} stroke={color} strokeWidth={1.4} fill="none" />
    <Rect x={5.4} y={5.5} width={5.2} height={7.2} rx={0.8} fill={color} />
  </Svg>
);

export const DropIcon = ({ size = 18, color = m.black }: P) => (
  <Svg width={size} height={size} viewBox="0 0 18 18">
    <Path
      d="M9 2.2c2.6 3.3 4.6 6 4.6 8.4A4.6 4.6 0 0 1 4.4 10.6C4.4 8.2 6.4 5.5 9 2.2z"
      stroke={color}
      strokeWidth={1.4}
      fill="none"
      strokeLinejoin="round"
    />
  </Svg>
);

export const BoltIcon = ({ size = 14, color = m.black }: P) => (
  <Svg width={size} height={size} viewBox="0 0 14 14">
    <Path d="M8 1L3 8h3.5L5.5 13 11 5.6H7.4z" fill={color} />
  </Svg>
);

export const SlidersIcon = ({ size = 22, color = m.white }: P) => (
  <Svg width={size} height={size} viewBox="0 0 22 22">
    <Path d="M3 7h9M17 7h2M3 15h2M10 15h9" stroke={color} strokeWidth={1.7} strokeLinecap="round" />
    <Circle cx={14.5} cy={7} r={2.3} stroke={color} strokeWidth={1.7} fill="none" />
    <Circle cx={7.5} cy={15} r={2.3} stroke={color} strokeWidth={1.7} fill="none" />
  </Svg>
);

export const PinIcon = ({ size = 18, color = m.muted }: P) => (
  <Svg width={size} height={size} viewBox="0 0 18 18">
    <Path d="M9 16s5.2-4.9 5.2-8.6A5.2 5.2 0 0 0 3.8 7.4C3.8 11.1 9 16 9 16z" stroke={color} strokeWidth={1.5} fill="none" />
    <Circle cx={9} cy={7.4} r={1.8} fill={color} />
  </Svg>
);

export const ClockIcon = ({ size = 18, color = m.muted }: P) => (
  <Svg width={size} height={size} viewBox="0 0 18 18">
    <Circle cx={9} cy={9} r={6.8} stroke={color} strokeWidth={1.5} fill="none" />
    <Path d="M9 5.3V9l2.6 1.6" stroke={color} strokeWidth={1.5} strokeLinecap="round" fill="none" />
  </Svg>
);

/**
 * Generic side-view car silhouette, drawn from scratch (stands in for the vehicle photos in the real app).
 * `van` draws a light panel van instead of a dark hatchback.
 */
export function CarArt({ width = 150, van = false }: { width?: number; van?: boolean }) {
  const h = width * 0.5;
  if (van) {
    return (
      <Svg width={width} height={h} viewBox="0 0 160 80">
        <Path d="M10 62V22c0-6 4-10 10-10h82c5 0 8 2 11 6l20 22 13 4c3 1 4 3 4 6v12z" fill="#e9ebef" stroke="#b9bec8" strokeWidth={1.5} />
        <Path d="M108 20l19 20h-25V20z" fill="#2b2f38" />
        <Rect x={18} y={20} width={78} height={30} rx={3} fill="#f7f8fa" />
        <Rect x={6} y={60} width={146} height={6} rx={3} fill="#2b2f38" />
        <Circle cx={36} cy={66} r={11} fill="#1d2027" />
        <Circle cx={36} cy={66} r={5} fill="#9aa0aa" />
        <Circle cx={124} cy={66} r={11} fill="#1d2027" />
        <Circle cx={124} cy={66} r={5} fill="#9aa0aa" />
      </Svg>
    );
  }
  return (
    <Svg width={width} height={h} viewBox="0 0 160 80">
      <Path
        d="M8 58c0-7 3-11 10-13l20-5 20-17c4-3 8-4 13-4h34c6 0 10 2 14 6l16 15 13 3c5 1 8 4 8 9v7c0 3-2 5-5 5H13c-3 0-5-2-5-5z"
        fill="#23262d"
      />
      <Path d="M48 40l16-14c3-2 5-3 9-3h14v17z" fill="#7d8592" />
      <Path d="M92 23h11c4 0 7 1 10 4l12 13H92z" fill="#7d8592" />
      <Path d="M14 52h10" stroke="#e8e9ec" strokeWidth={3} strokeLinecap="round" />
      <Path d="M145 50h6" stroke="#c9ced6" strokeWidth={3} strokeLinecap="round" />
      <Circle cx={40} cy={63} r={12} fill="#14161a" />
      <Circle cx={40} cy={63} r={6.5} fill="#b8bec8" />
      <Circle cx={122} cy={63} r={12} fill="#14161a" />
      <Circle cx={122} cy={63} r={6.5} fill="#b8bec8" />
    </Svg>
  );
}
