import { useCalibrationSummary } from '../api/queries';
import type { CalibrationSummary, MetricValue } from '../api/types';
import { pct } from '../lib/format';

function find(metrics: readonly MetricValue[], name: string, variant: MetricValue['variant']) {
  return metrics.find((m) => m.metric.toLowerCase() === name && m.variant === variant);
}

function interval(metric: MetricValue | undefined, digits: number): string {
  if (!metric || metric.ci_low === null || metric.ci_high === null) return 'no interval';
  return `${metric.ci_low.toFixed(digits)} to ${metric.ci_high.toFixed(digits)}`;
}

/** The summary line, for example `ECE 3.5%→1.7% · Brier 0.127→0.129`. Null when metrics are absent. */
export function calibrationText(summary: CalibrationSummary): string | null {
  const eceRaw = find(summary.metrics, 'ece', 'raw');
  const eceCal = find(summary.metrics, 'ece', 'calibrated');
  const brierRaw = find(summary.metrics, 'brier', 'raw');
  const brierCal = find(summary.metrics, 'brier', 'calibrated');
  if (!eceRaw || !eceCal || !brierRaw || !brierCal) return null;
  const ece = `ECE ${pct(eceRaw.value)}→${pct(eceCal.value)}`;
  const brier = `Brier ${brierRaw.value?.toFixed(3) ?? '–'}→${brierCal.value?.toFixed(3) ?? '–'}`;
  return `${ece} · ${brier}`;
}

/** Tooltip text with the confidence intervals. */
export function calibrationTitle(summary: CalibrationSummary): string {
  const eceRaw = find(summary.metrics, 'ece', 'raw');
  const eceCal = find(summary.metrics, 'ece', 'calibrated');
  const brierRaw = find(summary.metrics, 'brier', 'raw');
  const brierCal = find(summary.metrics, 'brier', 'calibrated');
  return [
    `Out of sample since ${summary.first_test_year}: ${summary.n_predictions.toLocaleString('en-US')} predictions, ${summary.n_snapshots.toLocaleString('en-US')} snapshots.`,
    `ECE raw ${interval(eceRaw, 4)}; calibrated ${interval(eceCal, 4)}.`,
    `Brier raw ${interval(brierRaw, 4)}; calibrated ${interval(brierCal, 4)}.`,
  ].join(' ');
}

interface CalibrationBadgeProps {
  /** `full` appends the out-of-sample note used on the spreads page. */
  variant?: 'compact' | 'full';
}

/** Out-of-sample calibration quality, so the reader knows how far to trust calibrated numbers. */
export function CalibrationBadge({ variant = 'compact' }: CalibrationBadgeProps) {
  const { data } = useCalibrationSummary();
  if (!data) return null;
  const text = calibrationText(data);
  if (!text) return null;
  const note = variant === 'full' ? ` (out of sample, ${data.first_test_year}+)` : '';
  return (
    <span className="badge" title={calibrationTitle(data)}>
      {text}
      {note}
    </span>
  );
}
