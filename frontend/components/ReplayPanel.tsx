import type { ReplayState } from "@/lib/types";
export function ReplayPanel({ state }: { state: ReplayState }) {
  return <section><div className="panel-heading"><h2>Replay controls</h2><span className="attention">UNAVAILABLE</span></div>
    <dl className="key-values"><div><dt>CURRENT SLOT</dt><dd>T+{state.currentSlot}</dd></div><div><dt>SEED</dt><dd>{state.seed}</dd></div></dl>
    <div className="control-row"><button disabled>RESET</button><button disabled>STEP +1H</button><button disabled>PLAY 8×</button></div>
    <div className="control-row"><button disabled>PRICE SPIKE</button><button disabled>CAPACITY LOSS</button></div>
    <div className="panel-footer">CONTROLS AWAIT REPLAY ENGINE / SHOCKS WILL BE SIMULATED</div></section>;
}
