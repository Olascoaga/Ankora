import type { ReproducibilityAssessment } from "../../types/api";

export function reproducibilityTitle(assessment: ReproducibilityAssessment | null): string {
  if (assessment?.status === "measured_reproducible") {
    return "Exact recorded repeats reproduced these outputs";
  }
  if (assessment?.status === "measured_variable") {
    return "Exact recorded repeats produced different outputs";
  }
  return "Repeat reproducibility was not assessed";
}

export function reproducibilityDetail(assessment: ReproducibilityAssessment | null): string {
  if (assessment?.status === "measured_reproducible") {
    return `${assessment.executions.length} completed executions with the same input fingerprint share one scientific-output fingerprint.`;
  }
  if (assessment?.status === "measured_variable") {
    const outputs = new Set(
      assessment.executions.map((execution) => execution.output_fingerprint_sha256),
    ).size;
    return `${assessment.executions.length} completed executions with the same input fingerprint produced ${outputs} scientific-output fingerprints. Read this exact execution, not its seed, as the result.`;
  }
  return "No second completed execution with the same inputs, recorded tool identity and protocol was compared. A seed supports a rerun request, not a claim that outputs will match.";
}
