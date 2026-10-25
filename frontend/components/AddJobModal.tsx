"use client";
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { SearchMultiSelect } from "./SearchMultiSelect";
import type { LocalTask } from "@/lib/backend-types";
import type { JobCreate } from "@/lib/types";
import { prepareJob } from "@/lib/workloads";
import type { DraftErrors, JobDraft } from "@/lib/workloads";

export function AddJobModal({ preview, currentSlot, regions, gpuTypes, tasks = [], simulationSlotSeconds, onClose, onSubmit }: {
  preview: boolean; currentSlot: number; regions: string[]; gpuTypes: string[]; tasks?: LocalTask[];
  onClose: () => void; onSubmit: (payload: JobCreate) => Promise<void>;
  simulationSlotSeconds?: number | null;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const id = useRef<string | null>(null);
  const busy = useRef(false);
  const [taskId, setTaskId] = useState("");
  const task = !preview ? tasks.find(row => row.id === taskId) : undefined;
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [errors, setErrors] = useState<DraftErrors>({});
  const [draft, setDraft] = useState<JobDraft>({
    name: "", resourceType: "GPU", resourceUnits: "1", gpuTypes: [],
    durationHours: "1", completeWithinHours: "6",
    regions: [...regions], budget: "", priority: "0",
  });
  useEffect(() => {
    const element = dialog.current;
    const previous = document.activeElement as HTMLElement | null;
    element?.showModal();
    return () => { element?.close(); previous?.focus(); };
  }, []);
  function field<K extends keyof JobDraft>(key: K, value: JobDraft[K]) {
    setDraft(current => ({ ...current, [key]: value }));
    setErrors(current => ({ ...current, [key]: undefined }));
    setSubmitError(null);
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy.current) return;
    id.current ??= `job-${crypto.randomUUID()}`;
    if (taskId && !task) { setSubmitError("This local task is no longer available. Choose a task again."); return; }
    const result = prepareJob(draft, currentSlot, id.current, task);
    setErrors(result.errors);
    if (!result.payload) {
      requestAnimationFrame(() => {
        const invalid = dialog.current?.querySelector<HTMLElement>('[aria-invalid="true"]');
        invalid?.closest("details")?.setAttribute("open", "");
        invalid?.focus();
      });
      return;
    }
    busy.current = true;
    setSubmitting(true); setSubmitError(null);
    try { await onSubmit(result.payload); onClose(); }
    catch (error) { setSubmitError(error instanceof Error ? error.message : "Could not create the job. Try again."); }
    finally { busy.current = false; setSubmitting(false); }
  }
  const error = (key: keyof JobDraft) => errors[key] ? <span id={`error-${key}`} className="field-error">{errors[key]}</span> : null;
  const attrs = (key: keyof JobDraft) => ({ "aria-invalid": Boolean(errors[key]), "aria-describedby": errors[key] ? `error-${key}` : undefined });
  return <dialog ref={dialog} className="job-modal" aria-labelledby="add-job-title" aria-describedby="add-job-description" onCancel={event => { event.preventDefault(); if (!busy.current) onClose(); }}>
    <form noValidate onSubmit={submit}>
      <div className="modal-heading"><div><h2 id="add-job-title">Add job</h2><p id="add-job-description">{preview ? "Create an example workload in this preview session." : simulationSlotSeconds ? `SIMULATED execution: each scheduling hour takes ${simulationSlotSeconds} seconds. No real compute is purchased.` : "Submit a workload to the scheduling portfolio."}</p></div><button type="button" disabled={submitting} onClick={onClose}>Close</button></div>
      <fieldset className="modal-fields" disabled={submitting}>
        <label>Job name<input autoFocus maxLength={120} value={draft.name} onChange={e => field("name", e.target.value)} {...attrs("name")} placeholder="e.g. nightly embeddings" />{error("name")}</label>
        {!preview && tasks.length > 0 && <label>Execution task<select value={taskId} onChange={event => { setTaskId(event.target.value); setErrors({}); setSubmitError(null); }}><option value="">Scheduling workload</option>{tasks.map(task => <option key={task.id} value={task.id}>{task.name} · LOCAL</option>)}</select></label>}
        {task ? <p className="form-note">{task.resourceUnits} CPU · Local execution · {task.name}. Execution follows the active dispatch policy or the Run local task control.</p> : <><div className="form-grid"><label>Work type<select value={draft.resourceType} onChange={e => field("resourceType", e.target.value as "CPU" | "GPU")}><option value="GPU">GPU workload</option><option value="CPU">CPU batch workload</option></select></label>
          <label>{draft.resourceType === "GPU" ? "GPUs required" : "CPU units required"}<input type="number" min="1" step="1" value={draft.resourceUnits} onChange={e => field("resourceUnits", e.target.value)} {...attrs("resourceUnits")} />{error("resourceUnits")}</label></div>
        {draft.resourceType === "GPU" && <SearchMultiSelect label="GPU models" options={gpuTypes.map(value => ({ value, label: value }))} values={draft.gpuTypes} onChange={values => field("gpuTypes", values)} error={errors.gpuTypes} hint="Select models your workload can run on. The scheduler may choose any one of them." />}</>}
        <div className="form-grid"><label>Duration (hours)<input type="number" min="1" step="1" value={draft.durationHours} onChange={e => field("durationHours", e.target.value)} {...attrs("durationHours")} />{error("durationHours")}</label>
          <label>Complete within (hours)<input type="number" min="1" step="1" value={draft.completeWithinHours} onChange={e => field("completeWithinHours", e.target.value)} {...attrs("completeWithinHours")} />{error("completeWithinHours")}</label></div>
        <p className="form-note">Duration is the time the job needs to run. “Complete within” is the total time allowed after submission, including waiting. For example: a 2-hour job completed within 6 hours has up to 4 hours to wait.</p>
        {!task && <SearchMultiSelect label="Allowed regions" options={regions.map(value => ({ value, label: ({ "eu-west-1": "Ireland", "eu-central-1": "Frankfurt", "us-east-1": "N. Virginia" } as Record<string, string>)[value] ?? value, detail: value }))} values={draft.regions} onChange={values => field("regions", values)} error={errors.regions} hint="All listed regions are selected initially. Limit the selection if your workload has residency requirements." />}
        <details><summary>Budget & priority</summary><div className="form-grid advanced-fields"><label>Maximum budget (USD)<input type="number" min="0" step="0.01" value={draft.budget} onChange={e => field("budget", e.target.value)} placeholder="No limit" {...attrs("budget")} />{error("budget")}</label>
          <label>Priority<select value={draft.priority} onChange={e => field("priority", e.target.value)}><option value="0">Normal</option><option value="1">High</option><option value="2">Urgent</option></select>{error("priority")}</label></div></details>
      </fieldset>
      {(submitError || errors.clock) && <p role="alert" className="notice error">{submitError ?? errors.clock}</p>}
      <div className="modal-actions"><span className="form-note">{preview ? "Preview only · resets on page reload" : "Creates a pending job · active dispatch policy applies"}</span><button type="button" disabled={submitting} onClick={onClose}>Cancel</button><button className="primary-button" type="submit" disabled={submitting}>{submitting ? "Adding…" : preview ? "Add preview job" : "Add job"}</button></div>
    </form>
  </dialog>;
}
