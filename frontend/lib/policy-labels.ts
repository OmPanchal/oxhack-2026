import type { Strategy } from "./types";

export const visiblePolicies: Strategy[] = ["FIFO", "CHEAPEST_NOW", "OPTIMIZER_WITH_ML"];

const names: Record<Strategy, string> = {
  FIFO: "FIFO",
  CHEAPEST_NOW: "Cheapest now",
  OPTIMIZER_WITH_NAIVE_FORECAST: "Optimizer / persistence",
  OPTIMIZER_WITH_ML: "Optimizer / ML requested",
};

export function policyPresentation(policy: Strategy, versions: string[] = [], status?: string) {
  if (policy !== "OPTIMIZER_WITH_ML") return { label: names[policy], note: null };
  const unique = [...new Set(versions)];
  const persistence = unique.filter(version => version.startsWith("persistence-v1") || version === "integration-persistence-v1");
  const learned = unique.filter(version => version.startsWith("lightgbm-price-"));
  const unknown = unique.length - persistence.length - learned.length;
  if (unique.length && persistence.length === unique.length) {
    const reason = unique.some(version => version === "persistence-v1:fallback-model-not-available")
      ? " This scenario predates the model's availability."
      : "";
    return { label: "Optimizer / persistence fallback", note: `ML not used. Only persistence forecasts were recorded.${reason}` };
  }
  if (learned.length && persistence.length && !unknown) return {
    label: "Optimizer / ML + persistence fallback",
    note: "Mixed forecast use: both ML and persistence fallback were recorded. This is not an ML-only result.",
  };
  if (learned.length && !unknown) return { label: "Optimizer / ML", note: "ML forecasts recorded for this replay." };
  if (unique.length) return { label: names[policy], note: "Forecast usage unverified. The supplied versions do not establish an ML-only result." };
  if (status === "UNAVAILABLE") return { label: "Optimizer / ML unavailable", note: "ML provider unavailable. No forecasts recorded." };
  return { label: names[policy], note: "No forecasts recorded yet." };
}

export function policyLabel(policy: Strategy, versions?: string[], status?: string) {
  return policyPresentation(policy, versions, status).label;
}
