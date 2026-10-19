import { useMemo } from 'react';
import type { DistributionResponse } from '../api/types';
import { ordColor } from '../lib/colors';
import { CdfOverlay, CdfPanel } from './CdfPanel';
import { xDomainFor } from './options';
import type { Layout, PlotSeries, View, XMode } from './options';

/** The page shows at most this many expirations; the grid always has this many slots. */
export const SLOTS = 4;
const GRID_GAP = 16;
const CARD_CHROME = 26;

interface CdfSmallMultiplesProps {
  data: DistributionResponse;
  view: View;
  layout: Layout;
  xMode: XMode;
  /** Width of the whole grid in pixels. */
  width: number;
  refreshing?: boolean;
}

/** Four fixed CDF + density slots (so the layout never jumps), or one shared overlay. */
export function CdfSmallMultiples({
  data,
  view,
  layout,
  xMode,
  width,
  refreshing,
}: CdfSmallMultiplesProps) {
  const expiries = data.expirations;
  const xDomain = useMemo(() => xDomainFor(expiries, xMode), [expiries, xMode]);
  const columns = width >= 720 ? 2 : 1;
  const panelWidth = Math.max(
    220,
    Math.floor((width - GRID_GAP * (columns - 1)) / columns) - CARD_CHROME,
  );
  const panelHeight = Math.round(Math.min(340, Math.max(260, panelWidth * 0.72)));

  if (layout === 'overlay') {
    const series: PlotSeries[] = [];
    expiries.slice(0, SLOTS).forEach((expiry, index) => {
      if (expiry.curve) series.push({ expiry, curve: expiry.curve, color: ordColor(index) });
    });
    const overlayWidth = Math.max(220, width - CARD_CHROME);
    return (
      <CdfOverlay
        series={series}
        view={view}
        xMode={xMode}
        xDomain={xDomain}
        width={overlayWidth}
        height={Math.round(Math.min(420, Math.max(300, overlayWidth * 0.5)))}
        refreshing={refreshing}
      />
    );
  }

  return (
    <div
      className="grid-multiples"
      style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`, gap: GRID_GAP }}
    >
      {Array.from({ length: SLOTS }, (_, slot) => (
        <CdfPanel
          key={slot}
          expiry={expiries[slot] ?? null}
          color={ordColor(slot)}
          view={view}
          xMode={xMode}
          xDomain={xDomain}
          width={panelWidth}
          height={panelHeight}
          refreshing={refreshing}
        />
      ))}
    </div>
  );
}
