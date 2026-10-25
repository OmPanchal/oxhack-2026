"use client";
import { useRef, useState } from "react";
import { api } from "@/lib/api";
import type { EngineState } from "@/lib/backend-types";

export function EngineControls({ state, onRefresh }: { state: EngineState; onRefresh: () => void }) {
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"NAIVE" | "ML" | null>(null);
  async function act(operation: () => Promise<unknown>) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(null);
    try { await operation(); } catch (error) { setError(error instanceof Error ? error.message : String(error)); }
    finally { lock.current = false; setBusy(false); onRefresh(); }
  }
  return <div className="engine-controls">
    <div className="control-row"><span className="tag">Live engine · {state.executionMode}</span><span className="muted">{state.dispatch.paused ? "New starts paused · running work continues" : "Dispatch active"} · {state.dataKind ?? "No market data"}</span>
      <label>Forecast <select value={mode ?? state.forecastMode} disabled={busy} onChange={event => setMode(event.target.value as "NAIVE" | "ML")}><option value="NAIVE">Persistence</option><option value="ML" disabled={!state.mlConfigured}>ML{state.mlConfigured ? "" : " · unavailable"}</option></select></label>
      <button disabled={busy} onClick={() => void act(async () => { const fresh = await api.engineState(); return api.optimize({ currentSlot: fresh.currentSlot, forecastMode: mode ?? fresh.forecastMode, executionMode: fresh.executionMode }); })}>{busy ? "Updating…" : "Replan"}</button>
      <button disabled={busy} onClick={() => void act(state.dispatch.paused ? api.resume : api.pause)}>{state.dispatch.paused ? "Resume new starts" : "Pause new starts"}</button>
    </div>
    {state.lastError && <p className="notice error" role="alert">{state.lastError.code}: {state.lastError.message}</p>}
    {state.dispatch.lastResumeError && <p className="notice error" role="alert">Resume: {state.dispatch.lastResumeError.message}</p>}
    {error && <p className="notice error" role="alert">{error}</p>}
  </div>;
}
