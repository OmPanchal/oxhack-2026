import type { Forecast, MarketSnapshot } from "./types";

export type QuoteKind = "OBSERVED" | "SIMULATED";
export function defaultQuoteKind(market: MarketSnapshot[], resource: string | undefined, currentSlot: number): QuoteKind {
  const relevant = market.filter(row => (!resource || resourceKey(row) === resource) && row.slot <= currentSlot);
  return relevant.some(row => row.dataKind === 'OBSERVED') ? 'OBSERVED'
    : relevant.some(row => row.dataKind === 'SIMULATED') ? 'SIMULATED' : 'OBSERVED';
}
export const regionName = (region: string) => ({ "eu-north-1": "Stockholm", "eu-west-1": "Ireland", "eu-west-2": "London", "eu-central-1": "Frankfurt", "us-east-1": "N. Virginia", "us-west-2": "Oregon", local: 'Local machine' } as Record<string, string>)[region] ?? region;
export const resourceKey = (row: Pick<MarketSnapshot, "resourceType" | "gpuType">) => JSON.stringify([row.resourceType, row.resourceType === "GPU" ? row.gpuType ?? null : null]);
export function resourceLabel(key: string): string {
  const [type, model] = JSON.parse(key) as [string, string | null];
  return type === "CPU" ? "CPU" : model ? `GPU / ${model}` : "GPU / unspecified model";
}
export function marketResources(market: MarketSnapshot[], forecasts: Forecast[], currentSlot: number): string[] {
  return [...new Set([
    ...market.filter(row => row.slot <= currentSlot && row.dataKind !== "FORECAST"),
    ...forecasts.filter(row => row.generatedAtSlot <= currentSlot),
  ].map(resourceKey))].sort();
}
export type ForecastRun = { key: string; issued: number; model: string; points: Forecast[] };
export function forecastRuns(forecasts: Forecast[], resource: string, region: string, currentSlot: number): ForecastRun[] {
  const groups = new Map<string, ForecastRun>();
  for (const row of forecasts) {
    if (resourceKey(row) !== resource || row.region !== region || row.generatedAtSlot > currentSlot || row.targetSlot <= row.generatedAtSlot || row.targetSlot > row.generatedAtSlot + 6 || !Number.isFinite(row.predictedPriceUsdPerUnitHour) || row.predictedPriceUsdPerUnitHour < 0) continue;
    const key = JSON.stringify([row.generatedAtSlot, row.modelVersion]);
    if (!groups.has(key)) groups.set(key, { key, issued: row.generatedAtSlot, model: row.modelVersion, points: [] });
    const run = groups.get(key)!;
    // A duplicate target replaces the previous received value, never a second plotted slot.
    run.points = [...run.points.filter(point => point.targetSlot !== row.targetSlot), row];
  }
  return [...groups.values()].map(run => ({ ...run, points: run.points.sort((a, b) => a.targetSlot - b.targetSlot) }))
    .sort((a, b) => b.issued - a.issued || a.model.localeCompare(b.model));
}
export function upcomingPoints(run: ForecastRun | undefined, currentSlot: number, horizon: number): Forecast[] {
  return run?.points.filter(point => point.targetSlot > currentSlot && point.targetSlot <= currentSlot + horizon) ?? [];
}
export type RegionQuote = { region: string; quote: MarketSnapshot | null; next: Forecast | null; issued: number | null };
export function compareRegions(market: MarketSnapshot[], forecasts: Forecast[], resource: string, kind: QuoteKind, currentSlot: number): RegionQuote[] {
  const relevant = market.filter(row => resourceKey(row) === resource && row.dataKind === kind && row.slot <= currentSlot);
  const regions = [...new Set([...relevant.map(row => row.region), ...forecasts.filter(row => resourceKey(row) === resource && row.generatedAtSlot <= currentSlot).map(row => row.region)])];
  return regions.map(region => {
    const quote = relevant.filter(row => row.region === region).sort((a, b) => b.slot - a.slot)[0] ?? null;
    const run = forecastRuns(forecasts, resource, region, currentSlot)[0];
    return { region, quote, next: run?.points.find(point => point.targetSlot === currentSlot + 1) ?? null, issued: run?.issued ?? null };
  }).sort((a, b) => (a.quote?.priceUsdPerUnitHour ?? Infinity) - (b.quote?.priceUsdPerUnitHour ?? Infinity) || a.region.localeCompare(b.region));
}
export function lowestCurrentQuote(rows: RegionQuote[], currentSlot: number, units: number): RegionQuote | null {
  if (!Number.isSafeInteger(units) || units < 1) return null;
  return [...rows].filter(row => row.quote && row.quote.slot === currentSlot && row.quote.availableUnits != null && row.quote.availableUnits >= units)
    .sort((a, b) => a.quote!.priceUsdPerUnitHour - b.quote!.priceUsdPerUnitHour || a.region.localeCompare(b.region))[0] ?? null;
}
export function price(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? "—" : `$${value.toFixed(value > 0 && value < .01 ? 6 : 3)}`;
}
export function probability(value: number | null): string {
  return value === null || !Number.isFinite(value) || value < 0 || value > 1 ? "Unknown" : `${(value * 100).toFixed(1)}%`;
}
export function bounds(row: Forecast): [number, number] | null {
  const lo = row.priceLowerBound, hi = row.priceUpperBound;
  return lo != null && hi != null && Number.isFinite(lo) && Number.isFinite(hi) && lo >= 0 && hi >= lo ? [lo, hi] : null;
}
export const slotLabel = (slot: number, currentSlot: number) => slot === currentSlot ? "Now" : slot > currentSlot ? `+${slot - currentSlot}h` : `−${currentSlot - slot}h`;
export type PlotPoint = { slot: number; value: number; quote?: MarketSnapshot; forecast?: Forecast };
export function plotPoints(history: MarketSnapshot[], predictions: Forecast[], currentSlot: number): PlotPoint[] {
  const quotes = new Map(history.filter(row => row.slot <= currentSlot && row.dataKind !== "FORECAST").map(row => [row.slot, row]));
  return [...quotes.values()].map(quote => ({ slot: quote.slot, value: quote.priceUsdPerUnitHour, quote } as PlotPoint))
    .concat(predictions.map(forecast => ({ slot: forecast.targetSlot, value: forecast.predictedPriceUsdPerUnitHour, forecast })))
    .sort((a, b) => a.slot - b.slot);
}
export function stepPath(points: PlotPoint[], x: (n: number) => number, y: (n: number) => number): string {
  return points.map((point, i) => `${i > 0 && point.slot === points[i - 1].slot + 1 ? `V${y(point.value)}` : `M${x(point.slot)} ${y(point.value)}`} H${x(point.slot + 1)}`).join(" ");
}
export function priceAxis(values: number[]): number[] {
  if (!values.length) return [0, .25, .5, .75, 1];
  const low = Math.min(...values), high = Math.max(...values);
  const span = Math.max(high - low, high * .1, .004);
  const rough = span / 4, power = 10 ** Math.floor(Math.log10(rough));
  const step = ([1, 2, 5, 10].find(n => n * power >= rough) ?? 10) * power;
  const first = Math.max(0, Math.floor((low - step * .25) / step) * step);
  const last = Math.max(first + step, Math.ceil((high + step * .25) / step) * step);
  return Array.from({ length: Math.round((last - first) / step) + 1 }, (_, i) => +(first + i * step).toPrecision(10));
}
