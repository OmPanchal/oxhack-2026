import type { PlotPoint } from "@/lib/market";
import { bounds, price, probability, slotLabel } from "@/lib/market";

export function ForecastInspector({ point, points, currentSlot, onSelect }: {
  point?: PlotPoint; points: PlotPoint[]; currentSlot: number; onSelect: (slot: number) => void;
}) {
  const forecast = point?.forecast;
  const interval = forecast ? bounds(forecast) : null;
  return <section className="forecast-inspector" aria-labelledby="forecast-inspection-title">
    <div className="panel-heading"><h2 id="forecast-inspection-title">Slot inspection</h2><span className="muted">{point ? forecast ? "Forecast" : point.quote?.dataKind === "SIMULATED" ? "Simulated quote" : "Observed quote" : "No data"}</span></div>
    {point ? <>
      <div className="inspection-lead"><label htmlFor="inspect-market-slot">Inspect slot</label><select id="inspect-market-slot" value={point.slot} onChange={event => onSelect(Number(event.target.value))}>
        {points.map(row => <option key={row.slot} value={row.slot}>{slotLabel(row.slot, currentSlot)} · slot {row.slot} · {row.forecast ? "forecast" : "quote"}</option>)}
      </select><p className="inspection-value">{price(point.value)}<span> / unit-hour</span></p>
        <p className="form-note">{forecast ? "Predicted price, not realized spend." : `Recorded ${point.slot === currentSlot ? "at the current slot" : `${currentSlot - point.slot}h before the current slot`}.`}</p>
      </div>
      <dl className="key-values">
        {forecast ? <>
          <div className="wide-detail"><dt>Price bounds</dt><dd>{interval ? `${price(interval[0])} – ${price(interval[1])}` : "Not available"}</dd></div>
          <div><dt>Availability probability</dt><dd>{probability(forecast.availabilityProbability)}</dd></div>
          <div><dt>Interruption probability</dt><dd>{probability(forecast.interruptionProbability)}</dd></div>
          <div><dt>Issued at</dt><dd>Slot {forecast.generatedAtSlot}</dd></div><div><dt>Issue age</dt><dd>{currentSlot - forecast.generatedAtSlot}h</dd></div>
          <div className="wide-detail"><dt>Model version</dt><dd>{forecast.modelVersion}</dd></div>
        </> : <>
          <div><dt>Available units</dt><dd>{point.quote?.availableUnits ?? "Unknown"}</dd></div><div><dt>Quote age</dt><dd>{currentSlot - point.slot}h</dd></div>
          <div className="wide-detail"><dt>Source</dt><dd>{point.quote?.source ?? "Unknown"}</dd></div>
        </>}
      </dl>
      <p className="panel-footer">{forecast ? "Bounds and probabilities are supplied by the backend. Coverage/calibration is not provided." : "Capacity is a snapshot, not a reservation."}</p>
    </> : <p className="empty">Select a region with quotes or forecasts to inspect a slot.</p>}
  </section>;
}
