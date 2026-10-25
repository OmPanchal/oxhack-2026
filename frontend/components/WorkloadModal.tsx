"use client";
import { useEffect, useId, useRef } from "react";
import type { DecisionDetail } from "@/lib/backend-types";
import type { Decision, Job } from "@/lib/types";
import { DecisionInspector } from "./DecisionInspector";
import { JobDetails } from "./JobDetails";

export function WorkloadModal({ job, decision, evidence, currentSlot, preview, onClose }: {
  job: Job; decision?: Decision; evidence?: DecisionDetail; currentSlot: number; preview: boolean; onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  useEffect(() => {
    const element = dialog.current;
    const previous = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    element?.showModal();
    document.body.style.overflow = "hidden";
    return () => {
      element?.close();
      document.body.style.overflow = previousOverflow;
      if (previous?.isConnected) previous.focus();
    };
  }, []);
  return <dialog ref={dialog} className="job-modal workload-modal" aria-labelledby={titleId} aria-describedby={descriptionId} onCancel={event => { event.preventDefault(); onClose(); }}>
    <div className="modal-heading"><div><h2 id={titleId}>{job.name}</h2><p id={descriptionId}>{job.id} · {job.status} · {preview ? "Example workload" : "Portfolio workload"}</p></div><button type="button" autoFocus onClick={onClose}>Close</button></div>
    <div className="workload-modal-content">
      <DecisionInspector job={job} decision={decision} evidence={evidence} currentSlot={currentSlot} preview={preview} />
      <JobDetails job={job} currentSlot={currentSlot} />
    </div>
  </dialog>;
}
