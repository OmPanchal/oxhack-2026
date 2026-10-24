"use client";
import { useEffect, useId, useRef, useState } from "react";
import type { Forecast, MarketSnapshot } from "@/lib/types";
import type { PlotPoint } from "@/lib/market";
import { bounds, price, priceAxis, slotLabel, stepPath } from "@/lib/market";

export function SlotPriceChart({ history, predictions, points, currentSlot, selectedSlot, onSelect }: {
  history: MarketSnapshot[]; predictions: Forecast[]; points: PlotPoint[]; currentSlot: number;
  selectedSlot: number | null; onSelect: (slot: number) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(760);
  const hintId = useId();
  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(280, entry.contentRect.width)));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const values = [...points.map(point => point.value), ...predictions.flatMap(row => bounds(row) ?? [])];
  const axis = priceAxis(values);
  const minSlot = points[0]?.slot ?? currentSlot, maxSlot = (points[points.length - 1]?.slot ?? currentSlot) + 1;
  const x = (slot: number) => 58 + (slot - minSlot) / (maxSlot - minSlot) * (width - 78);
  const y = (value: number) => 192 - (value - axis[0]) / (axis[axis.length - 1] - axis[0]) * 154;
  const tickStep = Math.max(1, Math.ceil((maxSlot - minSlot) / (width < 500 ? 3 : 6)));
  const ticks = Array.from({ length: Math.floor((maxSlot - minSlot) / tickStep) + 1 }, (_, i) => minSlot + i * tickStep);
  const quotePoints = points.filter(row => row.quote);
  const forecastPoints = points.filter(row => row.forecast);
  const selected = points.find(row => row.slot === selectedSlot);
  return <div className="market-plot" ref={container}>
    {points.length ? <svg className="market-chart-svg" viewBox={`0 0 ${width} 230`} role="group" tabIndex={0} aria-label="Hourly prices. Use left and right arrow keys to inspect slots." aria-describedby={hintId} onKeyDown={event => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault();
      const index = points.findIndex(row => row.slot === selectedSlot);
      const next = Math.max(0, Math.min(points.length - 1, (index < 0 ? 0 : index) + (event.key === "ArrowRight" ? 1 : -1)));
      onSelect(points[next].slot);
    }}>
      <title>Discrete hourly prices and forecast</title>
      {axis.map(value => <g key={value}><line x1="58" x2={width - 20} y1={y(value)} y2={y(value)} stroke="var(--line)" /><text x="50" y={y(value) + 4} textAnchor="end">{value.toFixed(value < .1 ? 3 : 2)}</text></g>)}
      {ticks.map((slot, i) => <text key={slot} x={x(slot)} y="216" textAnchor={i === 0 ? "start" : i === ticks.length - 1 ? "end" : "middle"}>{slotLabel(slot, currentSlot)}</text>)}
      {predictions.map(row => { const interval = bounds(row); return interval && <rect key={row.targetSlot} x={x(row.targetSlot)} y={y(interval[1])} width={x(row.targetSlot + 1) - x(row.targetSlot)} height={y(interval[0]) - y(interval[1])} fill="var(--range)" fillOpacity=".12" />; })}
      <path d={stepPath(quotePoints, x, y)} fill="none" stroke="var(--history)" strokeWidth="2" />
      <path d={stepPath(forecastPoints, x, y)} fill="none" stroke="var(--forecast)" strokeWidth="2" strokeDasharray="5 3" />
      {predictions.length > 0 && <g><line x1={x(predictions[0].targetSlot)} x2={x(predictions[0].targetSlot)} y1="30" y2="192" stroke="var(--muted)" strokeDasharray="3 4" /><text x={Math.min(x(predictions[0].targetSlot) + 6, width - 72)} y="18">Forecast</text></g>}
      {selected && <g><line x1={x(selected.slot + .5)} x2={x(selected.slot + .5)} y1="30" y2="192" stroke="var(--silver)" strokeDasharray="2 3" /><circle cx={x(selected.slot + .5)} cy={y(selected.value)} r="4" fill={selected.forecast ? "var(--forecast)" : "var(--history)"} /></g>}
      {points.map(point => <rect key={point.slot} x={x(point.slot)} y="30" width={Math.max(1, x(point.slot + 1) - x(point.slot))} height="162" fill="transparent" className="slot-hit-area" onClick={() => onSelect(point.slot)}><title>{`${slotLabel(point.slot, currentSlot)}: ${price(point.value)} per unit-hour, ${point.forecast ? "forecast" : point.quote?.dataKind.toLowerCase()}`}</title></rect>)}
    </svg> : <p className="empty">No prices in this window. Missing slots are never interpolated.</p>}
    <p id={hintId} className="plot-hint">Click a slot, use the chart arrow keys, or choose a slot in the inspection panel.</p>
    <div className="market-legend">{quotePoints.length > 0 && <span><i className="legend-history" />{history.some(row => row.dataKind === "SIMULATED") ? "Simulated quotes" : "Observed quotes"}</span>}{forecastPoints.length > 0 && <span><i className="legend-forecast" />Forecast</span>}{predictions.some(row => bounds(row)) && <span><i className="legend-bounds" />Provided range</span>}</div>
  </div>;
}
