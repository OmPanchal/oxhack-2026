"use client";
import { useEffect, useState } from "react";
import { loadTerminal, useMocks } from "@/lib/api";
import type { TerminalData } from "@/lib/types";
import { Portfolio } from "@/components/Portfolio";
import { MarketChart } from "@/components/MarketChart";
import { JobBlotter } from "@/components/JobBlotter";
import { DecisionInspector } from "@/components/DecisionInspector";
import { ReplayPanel } from "@/components/ReplayPanel";
import { ExecutionMonitor } from "@/components/ExecutionMonitor";
import { PolicyComparison } from "@/components/PolicyComparison";

export default function Home() {
  const [data, setData] = useState<TerminalData | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { loadTerminal().then(setData).catch((error: unknown) => setError(String(error))); }, []);
  return <main>
    <header><div><p className="eyebrow">BUY-SIDE COMPUTE / DEVELOPMENT TERMINAL</p>
      <h1>Compute Arbitrage Engine</h1><p>Schedule workloads across regions and time to minimize cost.</p></div>
      <span className="badge">{useMocks ? "SIMULATED FIXTURE" : "BACKEND CONNECTED MODE"}</span></header>
    <p className="notice">Scaffold: forecasting, optimization, replay, benchmarks and Docker execution await implementation.</p>
    {error && <p role="alert" className="notice">Backend unavailable: {error}</p>}
    {!data && !error && <p>Loading terminal…</p>}
    {data && <div className="grid">
      <Portfolio jobs={data.jobs} /><MarketChart market={data.market} forecasts={data.forecasts} />
      <JobBlotter jobs={data.jobs} /><DecisionInspector decisions={data.decisions} />
      <ExecutionMonitor /><ReplayPanel state={data.replay} /><PolicyComparison />
    </div>}
  </main>;
}
