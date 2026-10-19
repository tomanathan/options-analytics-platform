/** Quality-flag presentation: severity, icon and a one-line meaning for each `QualityFlag` value. */

export type FlagKind = 'info' | 'warning';

export interface FlagInfo {
  flag: string;
  kind: FlagKind;
  icon: string;
  label: string;
  meaning: string;
}

const INFO_ICON = 'ⓘ'; // circled i
const WARNING_ICON = '⚠'; // warning sign

const KNOWN: Record<string, Omit<FlagInfo, 'flag' | 'kind' | 'icon'> & { kind: FlagKind }> = {
  clipped: {
    kind: 'info',
    label: 'clipped',
    meaning: 'Some strike intervals had negative implied probability and were clipped to zero.',
  },
  monotonicity_repaired: {
    kind: 'info',
    label: 'monotonicity repaired',
    meaning: 'The raw CDF decreased somewhere; the curve was repaired to be non-decreasing.',
  },
  left_tail_uncovered: {
    kind: 'warning',
    label: 'left tail uncovered',
    meaning: 'No quoted strikes cover the low-price tail, so P(S<K) there is not observed.',
  },
  right_tail_uncovered: {
    kind: 'warning',
    label: 'right tail uncovered',
    meaning: 'No quoted strikes cover the high-price tail, so P(S<K) there is not observed.',
  },
  sparse: {
    kind: 'warning',
    label: 'sparse',
    meaning: 'Few usable quotes; the implied distribution is coarse.',
  },
  forward_unknown: {
    kind: 'warning',
    label: 'forward unknown',
    meaning: 'The forward price could not be inferred from put-call parity.',
  },
  no_calls: {
    kind: 'warning',
    label: 'no calls',
    meaning: 'No usable call quotes; the curve is built from puts only.',
  },
};

/** Presentation for one flag. Unknown flags are shown as warnings so nothing is hidden. */
export function describeFlag(flag: string): FlagInfo {
  const known = KNOWN[flag];
  if (known) {
    return {
      flag,
      kind: known.kind,
      icon: known.kind === 'info' ? INFO_ICON : WARNING_ICON,
      label: known.label,
      meaning: known.meaning,
    };
  }
  return {
    flag,
    kind: 'warning',
    icon: WARNING_ICON,
    label: flag.replace(/_/g, ' '),
    meaning: `Quality flag "${flag}".`,
  };
}

/** Flags in a stable display order: warnings first, then info, alphabetical within each. */
export function orderFlags(flags: readonly string[]): FlagInfo[] {
  return flags
    .map(describeFlag)
    .sort((a, b) =>
      a.kind === b.kind ? a.flag.localeCompare(b.flag) : a.kind === 'warning' ? -1 : 1,
    );
}
