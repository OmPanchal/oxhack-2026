"""Conservative risk defaults until an empirical model is fitted and validated."""
from typing import Literal

EvidenceStatus = Literal["NO_OBSERVATIONS", "SIMULATED_ONLY", "OBSERVED_UNCALIBRATED"]


def unknown_risk(evidence_status: EvidenceStatus = "NO_OBSERVATIONS") -> dict:
    """Counts and exposure alone do not define calibrated forecast probabilities."""
    if evidence_status not in ("NO_OBSERVATIONS", "SIMULATED_ONLY", "OBSERVED_UNCALIBRATED"):
        raise ValueError("Unknown evidence status")
    return {
        "availabilityProbability": None,
        "interruptionProbability": None,
        "evidenceStatus": evidence_status,
        "modelVersion": "unknown-risk-v1",
        "reason": "No calibrated risk model is available; retain unknown probabilities.",
    }
