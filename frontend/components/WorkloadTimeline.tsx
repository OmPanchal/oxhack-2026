"use client";
import { useEffect, useId, useRef, useState } from "react";
import type { FocusEvent, MouseEvent } from "react";
import { createPortal } from "react-dom";
import type { Decision, Job } from "@/lib/types";
import { deadlineBuffer, latestDecision } from "@/lib/decisions";
import { packedTimeline } from "@/lib/timeline";
import { jobHardware } from "@/lib/workloads";

type Hover = { jobs: Job[]; left: number; top?: number; bottom?: number; maxHeight: number };

export function WorkloadTimeline({ jobs, decisions, currentSlot, selectedId, onSelect, preview }: {
  jobs: Job[]; decisions: Decision[]; currentSlot: number; selectedId: string | null; onSelect: (id: string) => void; preview: boolean;
}) {
  const timeline = packedTimeline(jobs.map(job => ({ job, decision: latestDecision(decisions, job.id, currentSlot) })), currentSlot);
  const position = (slot: number) => (slot - timeline.origin) / (timeline.limit - timeline.origin) * 100;
  const [hover, setHover] = useState<Hover | null>(null);
  const hoverId = useId();
  const card = useRef<HTMLDivElement>(null);
  const dismissTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dismissed = useRef(false);
  const anchor = useRef<HTMLElement | null>(null);
  function keepOpen() { if (dismissTimer.current) clearTimeout(dismissTimer.current); }
  function closeSoon() { keepOpen(); dismissTimer.current = setTimeout(() => {
    if (document.activeElement !== anchor.current && !card.current?.contains(document.activeElement)) setHover(null);
  }, 160); }
  function show(event: MouseEvent<HTMLElement> | FocusEvent<HTMLElement>, values: Job[]) {
    if (dismissed.current) return;
    keepOpen();
    anchor.current = event.currentTarget;
    const rect = event.currentTarget.getBoundingClientRect();
    const width = Math.min(360, window.innerWidth - 32);
    // Place below when possible, otherwise above; keep the whole card on screen.
    const below = window.innerHeight - rect.bottom - 16;
    const above = rect.top - 16;
    const height = Math.min(480, Math.max(below, above));
    // Anchor the actual card edge, rather than reserving its maximum height.
    const placement = below >= height ? { top: rect.bottom + 8 } : { bottom: window.innerHeight - rect.top + 8 };
    setHover({ jobs: values, left: Math.max(16, Math.min(rect.left, window.innerWidth - width - 16)), ...placement, maxHeight: Math.max(120, height) });
  }
  function openJob(id: string) { keepOpen(); anchor.current?.focus(); setHover(null); onSelect(id); }
  useEffect(() => () => { if (dismissTimer.current) clearTimeout(dismissTimer.current); }, []);
  useEffect(() => {
    if (!hover) return;
    const dismiss = () => setHover(null);
    const scroll = (event: Event) => { if (!card.current?.contains(event.target as Node | null)) dismiss(); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { dismissed.current = true; const restore = card.current?.contains(document.activeElement); setHover(null); if (restore) anchor.current?.focus(); } };
    window.addEventListener("resize", dismiss);
    window.addEventListener("scroll", scroll, true);
    window.addEventListener("keydown", escape);
    return () => { window.removeEventListener("resize", dismiss); window.removeEventListener("scroll", scroll, true); window.removeEventListener("keydown", escape); };
  }, [hover]);
  function hoverProps(values: Job[]) {
    return {
      onMouseEnter: (event: MouseEvent<HTMLElement>) => { dismissed.current = false; show(event, values); },
      onMouseLeave: closeSoon,
      onFocus: (event: FocusEvent<HTMLElement>) => { if (event.currentTarget !== anchor.current) dismissed.current = false; show(event, values); },
      onBlur: (event: FocusEvent<HTMLElement>) => { if (!card.current?.contains(event.relatedTarget as Node | null)) closeSoon(); },
      "aria-describedby": hover?.jobs.length === values.length && values.every((job, i) => hover.jobs[i].id === job.id) ? hoverId : undefined,
    };
  }
  return <section aria-labelledby="timeline-heading">
    <div className="panel-heading"><h2 id="timeline-heading">Workload timeline</h2><span className="tag">{preview ? "Example plans" : "Planned windows"}</span></div>
    <div className="timeline-legend"><span><i className="legend-execution" />Planned execution</span><span><i className="legend-deadline deadline-dot-key" />Deadline</span><span>Solid line: now · slot {currentSlot}</span><span>Hover or focus for details · select a task for its full plan</span></div>
    {!jobs.length ? <div className="empty"><h3>No workloads to map</h3><p>Add a workload to see its deadline here. Execution bars appear when a plan is supplied.</p></div> : <>
      <div className="packed-scroll" role="region" aria-label="Compact workload timeline" tabIndex={0}>
        <div className="packed-chart" style={{ minWidth: Math.max(520, (timeline.limit - timeline.origin) * 48) }}>
          <div className="packed-axis" aria-label="Scheduling slots, one hour each">{timeline.ticks.map((slot, i) => <span key={slot} className={i === 0 ? "axis-first" : i === timeline.ticks.length - 1 ? "axis-last" : undefined} style={{ left: `${position(slot)}%` }}>Slot {slot}<small>{slot === currentSlot ? "Now" : slot > currentSlot ? `+${slot - currentSlot}h` : `−${currentSlot - slot}h`}</small></span>)}</div>
          <div className="packed-deadlines" aria-label="Workload deadlines">{timeline.deadlines.map(group => <button key={group.slot} className="packed-deadline" style={{ left: `${position(group.slot)}%` }} {...hoverProps(group.jobs)} onClick={event => group.jobs.length === 1 ? openJob(group.jobs[0].id) : show(event, group.jobs)} aria-label={`Deadline slot ${group.slot}: ${group.jobs.map(job => job.name).join(", ")}`}><span className="deadline-dot" aria-hidden="true" /></button>)}</div>
          <div className="packed-lanes">
            {timeline.ticks.map(slot => <span key={slot} className="packed-gridline" style={{ left: `${position(slot)}%` }} />)}
            <span className="packed-now" style={{ left: `${position(currentSlot)}%` }}><span>Now · {currentSlot}</span></span>
            {timeline.lanes.length ? timeline.lanes.map((lane, i) => <div className="packed-lane" key={i} aria-label={`Execution lane ${i + 1}`}>{lane.map(({ job, window }) => <button key={job.id} className="packed-task" style={{ left: `${window.plan!.left}%`, width: `${window.plan!.width}%` }} {...hoverProps([job])} aria-pressed={job.id === selectedId} aria-haspopup="dialog" aria-label={`${job.name}, planned slots ${window.plan!.start} to ${window.plan!.end}, deadline slot ${job.deadlineSlot}`} onClick={() => openJob(job.id)}><span>{job.id}</span></button>)}</div>) : <p className="packed-no-plans">No execution windows supplied.</p>}
          </div>
        </div>
      </div>
      {timeline.unplanned.length > 0 && <div className="packed-unplanned"><span className="muted">No execution plan ({timeline.unplanned.length})</span>{timeline.unplanned.map(({ job }) => <button key={job.id} className="text-button" {...hoverProps([job])} aria-haspopup="dialog" onClick={() => openJob(job.id)}>{job.id}</button>)}</div>}
    </>}
    <div className="panel-footer">Only overlapping execution windows use extra lanes. Hover or focus a coral dot to inspect its deadline and tasks. Bars show supplied plans.</div>
    {hover && createPortal(<div ref={card} id={hoverId} className="timeline-hover" role="region" aria-label="Timeline workload details" tabIndex={0} style={{ left: hover.left, top: hover.top, bottom: hover.bottom, maxHeight: hover.maxHeight }} onMouseEnter={keepOpen} onMouseLeave={closeSoon} onFocus={keepOpen} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) closeSoon(); }}>
      {hover.jobs.map(job => { const decision = latestDecision(decisions, job.id, currentSlot); return <div className="timeline-hover-job" key={job.id}>
        <h3>{job.name}</h3><p className="muted">{job.id} · {job.status} · {preview ? "Example" : "Portfolio workload"}</p>
        <dl><div><dt>Hardware</dt><dd>{job.resourceUnits} × {jobHardware(job)}</dd></div><div><dt>Duration</dt><dd>{job.durationSlots}h</dd></div><div><dt>Deadline</dt><dd>Slot {job.deadlineSlot}</dd></div><div><dt>Planned window</dt><dd>{decision?.plannedStartSlot != null && decision.plannedEndSlot != null ? `${decision.plannedStartSlot}–${decision.plannedEndSlot}` : "Unavailable"}</dd></div><div><dt>Deadline buffer</dt><dd>{deadlineBuffer(job.deadlineSlot, decision?.plannedEndSlot ?? null)}</dd></div><div><dt>Budget</dt><dd>{job.maxBudgetUsd === null ? "No limit" : `$${job.maxBudgetUsd.toFixed(2)}`}</dd></div><div><dt>Projected cost</dt><dd>{decision?.projectedCostUsd == null ? "Unavailable" : `$${decision.projectedCostUsd.toFixed(2)}`}</dd></div><div><dt>Region</dt><dd>{decision?.region ?? "Not selected"}</dd></div></dl>
        <p className="muted">Allowed regions: {job.allowedRegions.join(", ")}</p>
        <p>{decision ? `${decision.action}: ${decision.explanation}` : "No scheduling decision supplied."}</p>
        <button className="text-button" onClick={() => openJob(job.id)}>Open full details</button>
      </div>; })}
    </div>, document.body)}
  </section>;
}
