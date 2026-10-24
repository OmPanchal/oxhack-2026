import type { ReplayState } from "@/lib/types";
export function ReplayPanel({ state }: { state: ReplayState }) {
  return <section><h2>Historical replay & simulated shocks</h2><p>{state.status} · slot {state.currentSlot} · seed {state.seed}</p>
    <p>Connect controls after the deterministic replay engine is implemented.</p>
    <button disabled>Reset</button><button disabled>Step</button><button disabled>Simulated shock</button></section>;
}
