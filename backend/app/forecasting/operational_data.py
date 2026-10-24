"""Import authorized operational exports and summarize time-bounded evidence."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path

from pydantic import ValidationError

from app.forecasting.collect_spot import stamp, utc
from app.forecasting.operational_schemas import (
    ExecutionObservation, FulfillmentObservation, OperationalDataset, ResourceObservation,
)
from app.forecasting.risk_model import unknown_risk


def _pool(record: ResourceObservation) -> tuple:
    return (record.region, record.availability_zone or "", record.instance_type,
            record.resource_type, record.gpu_type or "")


def _pool_fields(key: tuple) -> dict:
    region, zone, instance, resource, gpu = key
    return dict(region=region, availabilityZone=zone or None, instanceType=instance,
                resourceType=resource, gpuType=gpu or None)


def _fulfillment_counts(records: list[FulfillmentObservation]) -> dict:
    counts = {outcome: sum(row.outcome == outcome for row in records)
              for outcome in ("FULFILLED", "PARTIAL", "UNAVAILABLE", "ERROR", "CENSORED")}
    return dict(requestCount=len(records), outcomeCounts=counts,
                resolvedCapacityLabels=counts["FULFILLED"] + counts["PARTIAL"] + counts["UNAVAILABLE"],
                fullFulfillmentEvents=counts["FULFILLED"],
                incompleteFulfillmentEvents=counts["PARTIAL"] + counts["UNAVAILABLE"])


def _execution_counts(records: list[ExecutionObservation]) -> dict:
    counts = {outcome: sum(row.outcome == outcome for row in records)
              for outcome in ("COMPLETED", "INTERRUPTED", "FAILED", "CENSORED")}
    # A fleet/episode contributes one episode-hour, independent of resource count.
    # Censored and failed runs contribute observed exposure, not negative labels.
    seconds = sum((row.observed_until - row.started_at).total_seconds() for row in records)
    censored_seconds = sum((row.observed_until - row.started_at).total_seconds()
                           for row in records if row.outcome == "CENSORED")
    return dict(executionCount=len(records), outcomeCounts=counts,
                interruptionEvents=counts["INTERRUPTED"], observedEpisodeHours=seconds / 3600,
                censoredEpisodeHours=censored_seconds / 3600)


def summarize_evidence(dataset: OperationalDataset, *, as_of: datetime | str | None = None) -> dict:
    """Use only final records already recorded by as_of; never infer future labels.

    This is an evidence inventory, not model training or a risk estimator. A later
    terminal record is omitted entirely, even if its execution started earlier.
    """
    cutoff = utc(as_of) if as_of is not None else dataset.provenance.retrieved_at
    if cutoff > dataset.provenance.retrieved_at:
        raise ValueError("asOf exceeds the export retrieval time")
    fulfillment = [r for r in dataset.fulfillment_observations if r.recorded_at <= cutoff]
    executions = [r for r in dataset.execution_observations if r.recorded_at <= cutoff]
    fulfillment_groups = defaultdict(list)
    execution_groups = defaultdict(list)
    for row in fulfillment:
        fulfillment_groups[(*_pool(row), row.requested_units)].append(row)
    for row in executions:
        execution_groups[(*_pool(row), row.resource_units)].append(row)
    fulfillment_summary = [dict(_pool_fields(key[:-1]), requestedUnits=key[-1],
                                **_fulfillment_counts(rows))
                           for key, rows in sorted(fulfillment_groups.items())]
    execution_summary = []
    for key, rows in sorted(execution_groups.items()):
        counts = _execution_counts(rows)
        execution_summary.append(dict(_pool_fields(key[:-1]), resourceUnits=key[-1], **counts,
                                      resourceUnitHours=counts["observedEpisodeHours"] * key[-1],
                                      exposureUnit="GPU-hour" if key[3] == "GPU" else "vCPU-hour"))
    if not fulfillment and not executions:
        evidence_status = "NO_OBSERVATIONS"
    elif dataset.provenance.data_kind == "SIMULATED":
        evidence_status = "SIMULATED_ONLY"
    else:
        evidence_status = "OBSERVED_UNCALIBRATED"
    return dict(schemaVersion="operational-evidence-v1", asOf=stamp(cutoff),
                dataKind=dataset.provenance.data_kind,
                fulfillment=_fulfillment_counts(fulfillment), execution=_execution_counts(executions),
                fulfillmentGroups=fulfillment_summary, executionGroups=execution_summary,
                risk=unknown_risk(evidence_status),
                limitations=[
                    "Counts describe this export; collection/sampling bias may remain.",
                    "ERROR and CENSORED requests are excluded from resolved capacity labels.",
                    "FAILED and CENSORED executions are not interruption-negative labels.",
                    "Exposure ends at observedUntil; no post-censoring outcome is inferred.",
                    "Runtime units remain separated by hardware, location and requested size.",
                    "Placement scores and price history are not outcome labels.",
                    "No calibrated probabilities, classification metrics or savings are computed.",
                ])


def import_observations(source: Path, output: Path, *, as_of: str | datetime | None = None) -> dict:
    """Validate completely before writing a new, checksummed dataset directory."""
    if output.exists():
        raise ValueError("Output exists; choose a new import directory")
    raw = source.read_bytes()
    dataset = OperationalDataset.model_validate_json(raw)
    summary = summarize_evidence(dataset, as_of=as_of)
    normalized = dataset.model_dump(mode="json", by_alias=True)
    normalized["fulfillmentObservations"].sort(key=lambda r: (r["recordedAt"], r["id"]))
    normalized["executionObservations"].sort(key=lambda r: (r["recordedAt"], r["id"]))
    files = {"observations.json": (json.dumps(normalized, indent=2, sort_keys=True) + "\n").encode(),
             "summary.json": (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode()}
    manifest = dict(schemaVersion="operational-import-v1", inputSha256=hashlib.sha256(raw).hexdigest(),
                    provenance=normalized["provenance"], asOf=summary["asOf"],
                    sha256={name: hashlib.sha256(body).hexdigest() for name, body in files.items()},
                    transformations=["Timezone-aware timestamps normalized to UTC", "Stable record ordering"],
                    note="observations.json contains the full export; summary.json is bounded by asOf")
    files["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    output.mkdir(parents=True, exist_ok=False)
    for name, body in files.items():
        (output / name).write_bytes(body)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Authorized export or labeled synthetic fixture")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--as-of", help="Only summarize records available by this timezone-aware timestamp")
    args = parser.parse_args()
    try:
        summary = import_observations(args.input, args.output, as_of=args.as_of)
    except ValidationError as exc:
        details = "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}"
                            for err in exc.errors(include_input=False, include_url=False))
        parser.exit(1, f"Operational export rejected: {details}\n")
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Operational import failed: {exc}\n")
    print(f"Saved {summary['dataKind']} evidence to {args.output}: "
          f"{summary['fulfillment']['requestCount']} requests, "
          f"{summary['execution']['executionCount']} executions; risk probabilities remain unknown.")


if __name__ == "__main__":
    main()
