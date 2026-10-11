/**
 * Exceedance axis for a gauge's percentile curve (the usual hydrology view): x = -log10(1 - p/100),
 * so p50, p90, p99 and p99.5 are evenly readable instead of crowded at the right edge. p100 is
 * drawn a little beyond p99.75.
 */
export function exceedanceX(p: number): number {
  return -Math.log10(Math.max(1 - p / 100, 0.0025));
}

/** A round grid step (1, 2 or 5 x 10^k) giving about five lines across a range. */
export function niceStep(range: number): number {
  if (!(range > 0)) return 1;
  const raw = range / 5;
  const k = 10 ** Math.floor(Math.log10(raw));
  const f = raw / k;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * k;
}
