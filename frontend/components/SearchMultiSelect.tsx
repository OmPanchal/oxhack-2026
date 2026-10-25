"use client";
import { useEffect, useId, useRef, useState } from "react";
export type SelectOption = { value: string; label: string; detail?: string };

export function SearchMultiSelect({ label, options, values, onChange, error, hint }: {
  label: string; options: SelectOption[]; values: string[]; onChange: (values: string[]) => void;
  error?: string; hint?: string;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const filtered = options.filter(option => `${option.label} ${option.value} ${option.detail ?? ""}`.toLowerCase().includes(query.trim().toLowerCase()));
  const selected = options.filter(option => values.includes(option.value));
  useEffect(() => {
    if (!open) return;
    search.current?.focus();
    function outside(event: PointerEvent) { if (!root.current?.contains(event.target as Node)) setOpen(false); }
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);
  return <div className="multi-select" ref={root} onKeyDown={event => {
    if (event.key === "Escape" && open) { event.preventDefault(); event.stopPropagation(); setOpen(false); trigger.current?.focus(); }
  }}>
    <span id={`${id}-label`} className="multi-label">{label}</span>
    <button type="button" ref={trigger} className="multi-trigger" aria-expanded={open} aria-controls={`${id}-choices`}
      aria-labelledby={`${id}-label ${id}-summary`} aria-invalid={Boolean(error)} aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined}
      onClick={() => { setOpen(value => !value); setQuery(""); }}>
      <span id={`${id}-summary`}>{selected.length ? selected.map(option => option.label).join(", ") : `Select ${label.toLowerCase()}`}</span><span className="muted">{selected.length ? `${selected.length} selected` : "Choose"}</span>
    </button>
    {open && <div id={`${id}-choices`} className="multi-choices" role="group" aria-labelledby={`${id}-label`}>
      <input ref={search} type="search" aria-label={`Search ${label.toLowerCase()}`} value={query} placeholder={`Search ${label.toLowerCase()}…`} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === "Enter") event.preventDefault(); }} />
      <div className="multi-actions"><span className="muted">{filtered.length} options</span><button type="button" className="text-button" disabled={!options.length} onClick={() => onChange(options.map(option => option.value))}>Select all</button><button type="button" className="text-button" disabled={!values.length} onClick={() => onChange([])}>Clear</button></div>
      <div className="multi-options">{filtered.map(option => <label className="multi-option" key={option.value}>
        <input type="checkbox" checked={values.includes(option.value)} onChange={() => onChange(values.includes(option.value) ? values.filter(value => value !== option.value) : [...values, option.value])} />
        <span>{option.label}{option.detail && <small>{option.detail}</small>}</span>
      </label>)}{!filtered.length && <p className="form-note">{options.length ? "No matching options. Try another search." : "No options available from this data source yet."}</p>}</div>
    </div>}
    {error ? <span id={`${id}-error`} className="field-error">{error}</span> : hint && <span id={`${id}-hint`} className="form-note">{hint}</span>}
  </div>;
}
