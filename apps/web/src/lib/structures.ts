import { interpolateLab } from 'd3-interpolate';
import type { PresetId, StructureDirection, StructureKind, StructureView } from '../api/types';
import { pct, usd } from './format';

/**
 * Structure vocabulary shared by the structures page, its chart and the outcome map: labels,
 * direction glyphs, kind colours and the diverging advantage scale. Returns are per dollar of
 * max loss; prices are dollars per share.
 */

export interface KindMeta {
  label: string;
  /** Short name for matrix cells. */
  short: string;
  direction: StructureDirection;
  /** Spreads are the four verticals and the condor; singles are outright long premium. */
  family: 'spread' | 'single';
  credit: boolean;
  /** CSS reference to the `--kind-*` token. */
  color: string;
}

/** Table order of the design spec; the API lists `kinds` in this order too. */
export const KIND_ORDER: readonly StructureKind[] = [
  'long_call',
  'long_put',
  'bull_call_spread',
  'bear_put_spread',
  'bull_put_spread',
  'bear_call_spread',
  'long_straddle',
  'long_strangle',
  'iron_condor',
];

const token = (kind: StructureKind) => `var(--kind-${kind.replace(/_/g, '-')})`;

export const KINDS: Readonly<Record<StructureKind, KindMeta>> = {
  long_call: {
    label: 'Long call',
    short: 'Call',
    direction: 'up',
    family: 'single',
    credit: false,
    color: token('long_call'),
  },
  long_put: {
    label: 'Long put',
    short: 'Put',
    direction: 'down',
    family: 'single',
    credit: false,
    color: token('long_put'),
  },
  bull_call_spread: {
    label: 'Bull call spread',
    short: 'Bull call',
    direction: 'up',
    family: 'spread',
    credit: false,
    color: token('bull_call_spread'),
  },
  bear_put_spread: {
    label: 'Bear put spread',
    short: 'Bear put',
    direction: 'down',
    family: 'spread',
    credit: false,
    color: token('bear_put_spread'),
  },
  bull_put_spread: {
    label: 'Bull put spread',
    short: 'Bull put',
    direction: 'up',
    family: 'spread',
    credit: true,
    color: token('bull_put_spread'),
  },
  bear_call_spread: {
    label: 'Bear call spread',
    short: 'Bear call',
    direction: 'down',
    family: 'spread',
    credit: true,
    color: token('bear_call_spread'),
  },
  long_straddle: {
    label: 'Long straddle',
    short: 'Straddle',
    direction: 'move',
    family: 'single',
    credit: false,
    color: token('long_straddle'),
  },
  long_strangle: {
    label: 'Long strangle',
    short: 'Strangle',
    direction: 'move',
    family: 'single',
    credit: false,
    color: token('long_strangle'),
  },
  iron_condor: {
    label: 'Iron condor',
    short: 'Condor',
    direction: 'range',
    family: 'spread',
    credit: true,
    color: token('iron_condor'),
  },
};

/** Literal values of the `--kind-*` tokens, checked against tokens.css by a test. */
export const KIND_HEX: Readonly<Record<StructureKind, string>> = {
  long_call: '#c98500',
  long_put: '#e66767',
  bull_call_spread: '#3987e5',
  bull_put_spread: '#9ec5f4',
  bear_put_spread: '#199e70',
  bear_call_spread: '#7fd8b4',
  long_straddle: '#9085e9',
  long_strangle: '#d55181',
  iron_condor: '#b0aea5',
};

export const DIRECTION_GLYPH: Readonly<Record<StructureDirection, string>> = {
  up: '↑',
  down: '↓',
  move: '↔',
  range: '⇄',
};

/** Credit structures are dashed so the hue is never the only cue. */
export const CREDIT_DASH = '6 4';

export const kindLabel = (kind: StructureKind | null | undefined): string =>
  kind ? KINDS[kind].label : '–';

/** "Bull call spread" -> "bull call spread", for use inside a sentence. */
export const kindNoun = (kind: StructureKind): string => KINDS[kind].label.toLowerCase();

export const kindDash = (kind: StructureKind): string | undefined =>
  KINDS[kind].credit ? CREDIT_DASH : undefined;

export interface PresetMeta {
  id: PresetId;
  label: string;
}

/** The six quantile presets of the design spec, in its order. */
export const PRESETS: readonly PresetMeta[] = [
  { id: 'up', label: 'Up, above the 75th percentile' },
  { id: 'up_moderate', label: 'Up, moderately (55th to 85th)' },
  { id: 'flat', label: 'Flat (25th to 75th)' },
  { id: 'down_moderate', label: 'Down, moderately (15th to 45th)' },
  { id: 'down', label: 'Down, below the 25th percentile' },
  { id: 'big_move', label: 'Big move, outside the 10th to 90th' },
];

export const PRESET_IDS: readonly PresetId[] = PRESETS.map((preset) => preset.id);

export interface ParsedLeg {
  /** +1 long, -1 short. */
  quantity: number;
  right: 'C' | 'P';
  /** $/sh. */
  strike: number;
}

/** "+1 C 185 / -1 C 195" -> two legs. Pieces that do not parse are dropped. */
export function parseLegs(legs: string): ParsedLeg[] {
  return legs.split('/').flatMap((piece) => {
    const match = /^\s*([+-]?\d+)\s+([CP])\s+([\d.]+)\s*$/.exec(piece);
    if (!match) return [];
    return [{ quantity: Number(match[1]), right: match[2] as 'C' | 'P', strike: Number(match[3]) }];
  });
}

/** The terminal prices of a view in words: "Above $186.50 and below $201.00". */
export function viewBounds(lo: number | null, hi: number | null, outside: boolean): string {
  if (outside) {
    if (lo !== null && hi !== null) return `Below ${usd(lo)} or above ${usd(hi)}`;
    if (lo !== null) return `Below ${usd(lo)}`;
    if (hi !== null) return `Above ${usd(hi)}`;
    return 'Nowhere';
  }
  if (lo !== null && hi !== null) return `Above ${usd(lo)} and below ${usd(hi)}`;
  if (lo !== null) return `Above ${usd(lo)}`;
  if (hi !== null) return `Below ${usd(hi)}`;
  return 'Anywhere';
}

/** "Above $186.50 and below $201.00: 30.0% calibrated, 27.0% market-implied." */
export function viewSentence(view: StructureView): string {
  return `${viewBounds(view.lo, view.hi, view.outside)}: ${pct(view.prob)} calibrated, ${pct(view.prob_market)} market-implied.`;
}

/** Literal poles of the diverging scale, mirroring `--div-*` in tokens.css. */
export const DIV_HEX = { cool: '#256abf', mid: '#383835', warm: '#b04a3c' } as const;

/** An advantage of this many multiples (or more) takes the full pole colour. */
export const ADVANTAGE_SATURATION = 1;

const toCool = interpolateLab(DIV_HEX.mid, DIV_HEX.cool);
const toWarm = interpolateLab(DIV_HEX.mid, DIV_HEX.warm);

/**
 * Cell colour for `advantage` (spread minus single return if right): cool where the spread
 * returns more, warm where the single does, grey near zero. Null (one side missing) is grey.
 */
export function advantageColor(advantage: number | null | undefined): string {
  if (typeof advantage !== 'number' || !Number.isFinite(advantage)) return DIV_HEX.mid;
  const t = Math.min(1, Math.abs(advantage) / ADVANTAGE_SATURATION);
  return advantage >= 0 ? toCool(t) : toWarm(t);
}
