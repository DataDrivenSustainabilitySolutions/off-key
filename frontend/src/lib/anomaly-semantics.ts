export const formatAnomalyTailProbability = (tailProbability: number): string =>
  tailProbability > 0 && tailProbability < 0.0001 ? tailProbability.toExponential(2) : tailProbability.toFixed(4);

export const isProbabilityAnomalyValue = (
  valueType: string | null | undefined
): valueType is "tail_pvalue" | "conformal_pvalue" =>
  valueType === "tail_pvalue" || valueType === "conformal_pvalue";

/** A silence alarm's value: how long the reading had sent nothing. */
export const isSilenceAnomalyValue = (valueType: string | null | undefined) =>
  valueType === "silence_seconds";

const formatSilence = (seconds: number): string => {
  if (seconds < 120) return `${Math.round(seconds)} s`;
  if (seconds < 7200) return `${Math.round(seconds / 60)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
};

export const formatAnomalyValue = (
  value: number,
  valueType: string | null | undefined
): string =>
  isProbabilityAnomalyValue(valueType)
    ? formatAnomalyTailProbability(value)
    : isSilenceAnomalyValue(valueType)
      ? formatSilence(value)
      : value.toFixed(2);

export const getAnomalyValueLabel = (
  valueType: string | null | undefined
): string => {
  if (valueType === "anomaly_score") {
    return "Anomaly score";
  }
  if (valueType === "conformal_pvalue") {
    return "Conformal p-value";
  }
  if (valueType === "tail_pvalue") {
    return "Tail p-value";
  }
  if (isSilenceAnomalyValue(valueType)) {
    return "Silent for";
  }
  return "Legacy score";
};
