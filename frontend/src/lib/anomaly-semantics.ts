export const formatAnomalyTailProbability = (tailProbability: number): string =>
  tailProbability > 0 && tailProbability < 0.0001 ? tailProbability.toExponential(2) : tailProbability.toFixed(4);

export const isProbabilityAnomalyValue = (
  valueType: string | null | undefined
): valueType is "tail_pvalue" | "conformal_pvalue" =>
  valueType === "tail_pvalue" || valueType === "conformal_pvalue";

export const formatAnomalyValue = (
  value: number,
  valueType: string | null | undefined
): string =>
  isProbabilityAnomalyValue(valueType)
    ? formatAnomalyTailProbability(value)
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
  return "Legacy score";
};
