import type { ReplayState } from "@/lib/types";
import type { ReplayScenario } from "@/lib/replay-view";

export function ReplayPanel({ state, scenarios = [], scenarioId, index = 0, playing = false, speed = 1, onScenario, onReset, onStep, onPlay, onSpeed }: {
  state: ReplayState; scenarios?: ReplayScenario[]; scenarioId?: string; index?: number; playing?: boolean; speed?: number;
  onScenario?: (id: string) => void; onReset?: () => void; onStep?: () => void; onPlay?: () => void; onSpeed?: (speed: number) => void;
}) {
  const scenario = scenarios.find(row => row.id === scenarioId);
  const done = !!scenario && index === scenario.frames.length - 1;
  return <section className="replay-control-panel" aria-labelledby="replay-heading">
    <div className="panel-heading"><h2 id="replay-heading">Replay controls</h2><span className="tag">{scenario ? "Prepared preview" : state.status === "NOT_IMPLEMENTED" ? "Unavailable" : state.status}</span></div>
    <div className="replay-toolbar">
      {scenario && <>
        <label>Scenario<select value={scenarioId} onChange={event => onScenario?.(event.target.value)}>{scenarios.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
      </>}
      <div className="replay-toolbar-actions"><button onClick={onReset} disabled={!scenario}>Reset</button><button onClick={onStep} disabled={!scenario || done || playing}>Next event</button><button className="primary-button" onClick={onPlay} disabled={!scenario || done} aria-pressed={playing}>{playing ? "Pause" : "Play"}</button></div>
      <p className="replay-playback-status muted" role="status">{scenario ? `${done ? "Complete" : playing ? "Playing" : "Paused"} · Slot ${state.currentSlot} · ${index + 1}/${scenario.frames.length}` : `Slot ${state.currentSlot} · Seed ${state.seed}`}</p>
    </div>
    {scenario && <details className="replay-playback-options"><summary>Playback speed</summary><label>Advance events<select aria-label="Playback speed" value={speed} onChange={event => onSpeed?.(Number(event.target.value))}><option value={1}>1 event / 2 seconds</option><option value={2}>1 event / second</option><option value={4}>2 events / second</option></select></label></details>}
    <p className="replay-description">{scenario ? `${scenario.description} Changing scenario restarts the preview.` : "Replay actions are not connected yet. No example events are shown in Backend data."}</p>
  </section>;
}
