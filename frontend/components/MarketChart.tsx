"use client";
import { useState } from "react";
import type { Forecast, MarketSnapshot } from "@/lib/types";
import { compareRegions, forecastRuns, lowestCurrentQuote, marketResources, plotPoints, price, regionName, resourceKey, resourceLabel, upcomingPoints } from "@/lib/market";
import type { QuoteKind } from "@/lib/market";
import { ForecastInspector } from "./ForecastInspector";
import { SlotPriceChart } from "./SlotPriceChart";

export function MarketChart({ market, forecasts, preview, currentSlot }: { market: MarketSnapshot[]; forecasts: Forecast[]; preview: boolean; currentSlot: number }) {
  const resources = marketResources(market, forecasts, currentSlot);
  const [resourceChoice, setResourceChoice] = useState("");
  const [kind, setKind] = useState<QuoteKind>(preview ? "SIMULATED" : "OBSERVED");
  const [unitsText, setUnitsText] = useState("1");
  const [regionChoice, setRegionChoice] = useState("");
  const [runChoice, setRunChoice] = useState("");
  const [horizon, setHorizon] = useState(6);
  const [slotChoice, setSlotChoice] = useState<number | null>(null);
  const resource = resources.includes(resourceChoice) ? resourceChoice : resources.find(key => JSON.parse(key)[0] === "GPU") ?? resources[0];
  const units = Number(unitsText), validUnits = Number.isSafeInteger(units) && units > 0;
  const rows = resource ? compareRegions(market, forecasts, resource, kind, currentSlot) : [];
  const best = validUnits ? lowestCurrentQuote(rows, currentSlot, units) : null;
  const region = rows.some(row => row.region === regionChoice) ? regionChoice : best?.region ?? rows[0]?.region;
  const runs = region && resource ? forecastRuns(forecasts, resource, region, currentSlot) : [];
  const run = runs.find(row => row.key === runChoice) ?? runs[0];
  const predictions = upcomingPoints(run, currentSlot, horizon);
  const history = market.filter(row => row.region === region && resourceKey(row) === resource && row.dataKind === kind && row.slot <= currentSlot && row.slot >= Math.max(0, currentSlot - 5)).sort((a, b) => a.slot - b.slot);
  const points = plotPoints(history, predictions, currentSlot);
  const point = points.find(row => row.slot === slotChoice) ?? points.find(row => row.forecast) ?? points[points.length - 1];
  function selectRegion(value: string) { setRegionChoice(value); setRunChoice(""); setSlotChoice(null); }
  return <div className="market-workspace">
    <section aria-labelledby="regional-comparison-title">
      <div className="panel-heading"><h2 id="regional-comparison-title">Regional comparison</h2><span className="muted">As of slot {currentSlot} · USD / unit-hour</span></div>
      <div className="market-filters">
        <label>Resource<select aria-label="Market resource" disabled={!resources.length} value={resource ?? ""} onChange={event => { setResourceChoice(event.target.value); selectRegion(""); }}>{!resources.length && <option value="">No resources received</option>}{resources.map(key => <option key={key} value={key}>{resourceLabel(key)}</option>)}</select></label>
        <label>Quote data<select aria-label="Quote data kind" value={kind} onChange={event => { setKind(event.target.value as QuoteKind); setSlotChoice(null); }}><option value="OBSERVED">Observed</option><option value="SIMULATED">Simulated</option></select></label>
        <label className="units-field">Units required<input aria-label="Market units required" type="number" min="1" step="1" value={unitsText} aria-invalid={!validUnits} onChange={event => setUnitsText(event.target.value)} /></label>
      </div>
      <p className="comparison-finding" role="status">{!validUnits ? "Enter a positive whole number of units to compare capacity." : best ? <><strong>{regionName(best.region)}</strong> has the lowest current quote that covers {units} {units === 1 ? "unit" : "units"}: <strong>{price(best.quote!.priceUsdPerUnitHour)}</strong> / unit-hour.</> : "No current quote in this view covers the requested capacity."}</p>
      <div className="table-scroll"><table className="regional-table"><thead><tr><th>Region</th><th className="numeric">Current quote</th><th className="numeric">Available units</th><th className="numeric">Next hour forecast</th><th>Quote age</th><th>Data</th></tr></thead>
        <tbody>{rows.map(row => { const quote = row.quote; const age = quote ? currentSlot - quote.slot : null; const capacity = quote && validUnits && quote.availableUnits < units; return <tr key={row.region} className={row.region === region ? "selected" : ""}>
          <td><button className="row-select region-select" aria-pressed={row.region === region} onClick={() => selectRegion(row.region)}>{regionName(row.region)}<span className="cell-note muted">{row.region}</span></button>{best?.region === row.region && <span className="cell-note muted">Lowest current quote</span>}</td>
          <td className="numeric" data-label="Current quote">{price(quote?.priceUsdPerUnitHour)}</td><td className="numeric" data-label="Available units"><span className={capacity ? "attention" : ""}>{quote?.availableUnits.toLocaleString("en-US") ?? "—"}</span>{capacity && <span className="cell-note attention">Below request</span>}</td>
          <td className="numeric" data-label="Next hour forecast">{price(row.next?.predictedPriceUsdPerUnitHour)}{row.next && row.issued !== null && row.issued < currentSlot && <span className="cell-note muted">Issue {currentSlot - row.issued}h old</span>}</td>
          <td data-label="Quote age" className={age !== null && age > 0 ? "attention" : "muted"}>{age === null ? "No quote" : age === 0 ? "Current" : `${age}h old`}</td><td data-label="Data" className="muted">{quote ? quote.dataKind === "OBSERVED" ? "Observed" : "Simulated" : "Unavailable"}</td>
        </tr>; })}</tbody></table></div>
      {!rows.length && <p className="empty">No regional quotes or forecasts for this resource. Backend mode never substitutes preview data.</p>}
      <div className="panel-footer"><span>Only matching resource types and GPU models are compared. Stale quotes are not ranked as current opportunities.</span><span>Capacity is not a reservation.</span></div>
    </section>
    {region && resource && <div className="market-inspection-layout">
      <section aria-labelledby="trajectory-title">
        <div className="panel-heading"><div><h2 id="trajectory-title">{regionName(region)} · {resourceLabel(resource)}</h2><p className="form-note">{preview ? "Example prices and predictions" : "Quotes and model predictions"} · USD / unit-hour</p></div><span className="muted">{region}</span></div>
        <div className="forecast-controls"><label>Forecast issue<select aria-label="Forecast issue" disabled={!runs.length} value={run?.key ?? ""} onChange={event => { setRunChoice(event.target.value); setSlotChoice(null); }}>{!runs.length && <option value="">No forecasts received</option>}{runs.map(row => <option key={row.key} value={row.key}>Slot {row.issued} · {row.model}</option>)}</select></label>
          <label>Look ahead<select aria-label="Forecast horizon" value={horizon} onChange={event => { setHorizon(Number(event.target.value)); setSlotChoice(null); }}><option value="1">1 hour</option><option value="3">3 hours</option><option value="6">6 hours</option></select></label></div>
        {run && <p className={`forecast-freshness ${run.issued < currentSlot ? "attention" : "muted"}`}>{run.issued === currentSlot ? "Issued at the current slot." : `Forecast issue is ${currentSlot - run.issued}h old.`} {predictions.length} of {horizon} future slots supplied in this window.</p>}
        {!predictions.length && <p className="forecast-freshness muted">No upcoming forecast points in this window. Available market history remains visible.</p>}
        <SlotPriceChart history={history} predictions={predictions} points={points} currentSlot={currentSlot} selectedSlot={point?.slot ?? null} onSelect={setSlotChoice} />
        <div className="panel-footer">{preview ? "Simulated history and hand-authored forecast examples. No trained model is represented." : "Latest six hours of matching quotes; one selected model issue. Missing observations are left as gaps."}</div>
      </section>
      <ForecastInspector point={point} points={points} currentSlot={currentSlot} preview={preview} onSelect={setSlotChoice} />
    </div>}
  </div>;
}
