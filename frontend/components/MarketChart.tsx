import type { Forecast, MarketSnapshot } from "@/lib/types";
export function MarketChart({ market, forecasts }: { market: MarketSnapshot[]; forecasts: Forecast[] }) {
  return <section><h2>Regional market & forecasts</h2><table><thead><tr><th>Region</th><th>USD / unit-hour</th><th>Data</th></tr></thead>
    <tbody>{market.map((row, i) => <tr key={i}><td>{row.region}</td><td>${row.priceUsdPerUnitHour.toFixed(2)}</td><td>{row.dataKind}</td></tr>)}</tbody></table>
    <p>{forecasts.length} forecast points. Person 3: add Recharts trajectories and uncertainty bands when forecasts are available.</p></section>;
}
