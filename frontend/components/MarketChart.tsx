"use client";
import { useState } from "react";
import type { Forecast, MarketSnapshot } from "@/lib/types";

const seriesKey = (row: MarketSnapshot | Forecast) => `${row.region} / ${row.gpuType ?? row.resourceType}`;
type Point = { slot: number; price: number };

export function MarketChart({ market, forecasts, preview }: { market: MarketSnapshot[]; forecasts: Forecast[]; preview: boolean }) {
  const keys = [...new Set([...market, ...forecasts].map(seriesKey))];
  const [selection, setSelection] = useState("");
  const selected = keys.includes(selection) ? selection : keys[0];
  const history = market.filter(row => seriesKey(row) === selected).sort((a, b) => a.slot - b.slot);
  const allPredictions = forecasts.filter(row => seriesKey(row) === selected);
  const generation = Math.max(...allPredictions.map(row => row.generatedAtSlot));
  const predictions = allPredictions.filter(row => row.generatedAtSlot === generation).sort((a, b) => a.targetSlot - b.targetSlot);
  const points = [...history.map(row => ({ slot: row.slot, price: row.priceUsdPerUnitHour })),
    ...predictions.map(row => ({ slot: row.targetSlot, price: row.predictedPriceUsdPerUnitHour }))];
  const minSlot = points.length ? Math.min(...points.map(p => p.slot)) : 0;
  const maxSlot = points.length ? Math.max(...points.map(p => p.slot)) + 1 : 6;
  const prices = [...points.map(p => p.price), ...predictions.flatMap(row => [row.priceLowerBound, row.priceUpperBound].filter((n): n is number => n !== null))];
  const lo = prices.length ? Math.max(0, Math.min(...prices) * .9) : 0;
  const hi = prices.length ? Math.max(lo + .1, Math.max(...prices) * 1.06) : 1;
  const x = (slot: number) => 52 + (slot - minSlot) / (maxSlot - minSlot) * 812;
  const y = (price: number) => 208 - (price - lo) / (hi - lo) * 180;
  const step = (values: Point[]) => values.map((p, i) => i ? `H${x(p.slot)} V${y(p.price)}` : `M${x(p.slot)} ${y(p.price)}`).join(" ") + (values.length ? ` H${x(values[values.length - 1].slot + 1)}` : "");
  const tickCount = Math.min(8, maxSlot - minSlot + 1);
  const ticks = Array.from({ length: tickCount }, (_, i) => Math.round(minSlot + (maxSlot - minSlot) * i / Math.max(1, tickCount - 1)));
  return <section aria-labelledby="market-heading"><div className="panel-heading"><h2 id="market-heading">Regional prices</h2><span className="muted">USD / UNIT-HOUR · 1H SLOTS</span></div>
    <div className="chart-controls">{keys.map(key => <button key={key} aria-pressed={key === selected} onClick={() => setSelection(key)}>{key}</button>)}</div>
    <div className="table-scroll">{points.length ? <svg className="chart" viewBox="0 0 900 244" role="img" aria-label={`${selected}: discrete hourly prices and forecast. ${preview ? "Hand-authored simulated example." : "Backend data."}`}>
      <title>{`${selected} / hourly step prices`}</title>
      {predictions.length > 0 && <rect x={x(predictions[0].targetSlot)} y="20" width={x(maxSlot) - x(predictions[0].targetSlot)} height="188" fill="var(--range)" fillOpacity=".025" />}
      {[0, 1, 2, 3, 4].map(i => { const price = lo + (hi - lo) * i / 4; return <g key={i}><line x1="52" x2="864" y1={y(price)} y2={y(price)} stroke="var(--line)" /><text x="44" y={y(price) + 3} textAnchor="end">{price.toFixed(2)}</text></g>; })}
      {ticks.map(slot => <g key={slot}><line x1={x(slot)} x2={x(slot)} y1="28" y2="208" stroke="var(--line)" /><text x={x(slot)} y="228" textAnchor="middle">T+{String(slot).padStart(2, "0")}</text></g>)}
      {predictions.map(row => row.priceLowerBound != null && row.priceUpperBound != null && <rect key={row.targetSlot} x={x(row.targetSlot)} y={y(row.priceUpperBound)} width={x(row.targetSlot + 1) - x(row.targetSlot)} height={Math.max(0, y(row.priceLowerBound) - y(row.priceUpperBound))} fill="var(--range)" fillOpacity=".12" />)}
      <path d={step(history.map(row => ({ slot: row.slot, price: row.priceUsdPerUnitHour })))} fill="none" stroke="var(--history)" strokeWidth="2" />
      <path d={step(predictions.map(row => ({ slot: row.targetSlot, price: row.predictedPriceUsdPerUnitHour })))} fill="none" stroke="var(--forecast)" strokeWidth="2" strokeDasharray="5 3" />
      {predictions.length > 0 && <g><line x1={x(predictions[0].targetSlot)} x2={x(predictions[0].targetSlot)} y1="20" y2="208" stroke="var(--muted)" strokeDasharray="3 4" /><text x={x(predictions[0].targetSlot) + 6} y="14">FORECAST →</text></g>}
    </svg> : <p className="empty">No market or forecast data available.</p>}</div>
    <div className="chart-legend"><span className="chart-history">━ {preview ? "SIMULATED HISTORY" : "MARKET HISTORY"}</span><span className="chart-forecast">┄ {preview ? "EXAMPLE FORECAST / RANGE" : "FORECAST / PROVIDED BOUNDS"}</span><span className="muted">{preview ? "ILLUSTRATIVE RANGE · NOT CALIBRATED" : "STEP UPDATES / NO INTERPOLATION"}</span></div>
    <div className="table-scroll"><table><thead><tr><th>REGION / RESOURCE</th><th className="numeric">LATEST SLOT</th><th className="numeric">USD/U-H</th><th className="numeric">AVAILABLE</th><th>PROVENANCE</th></tr></thead>
      <tbody>{keys.map(key => { const latest = market.filter(row => seriesKey(row) === key).sort((a, b) => b.slot - a.slot)[0]; return latest && <tr key={key}><td>{key}</td><td className="numeric">T+{latest.slot}</td><td className="numeric positive">{latest.priceUsdPerUnitHour.toFixed(3)}</td><td className="numeric">{latest.availableUnits}</td><td className={latest.dataKind === "SIMULATED" ? "attention" : "muted"}>{latest.dataKind}</td></tr>; })}</tbody></table></div>
  </section>;
}
