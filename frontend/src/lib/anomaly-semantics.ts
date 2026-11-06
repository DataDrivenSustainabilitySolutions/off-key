export const getAnomalyTailProbabilityClassName = (
  tailProbability: number
): string => {
  if (tailProbability <= 0.001) {
    return "bg-red-100 text-red-800 dark:bg-red-900/35 dark:text-red-200";
  }
  if (tailProbability <= 0.005) {
    return "bg-orange-100 text-orange-800 dark:bg-orange-900/35 dark:text-orange-200";
  }
  return "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/35 dark:text-yellow-200";
};

function formatSignal(value: number, digits: number): string {
  const rounded = value.toFixed(digits);
  return value !== 0 && Number(rounded) === 0 ? Number(value.toPrecision(3)).toString() : rounded;
}

export const formatAnomalyTailProbability = (tailProbability: number): string =>
  formatSignal(tailProbability, 4);

export const isProbabilityAnomalyValue = (
  valueType: string | null | undefined
): valueType is "tail_pvalue" | "conformal_pvalue" =>
  valueType === "tail_pvalue" || valueType === "conformal_pvalue";

export const getAnomalyValueClassName = (
  value: number,
  valueType: string | null | undefined
): string =>
  isProbabilityAnomalyValue(valueType)
    ? getAnomalyTailProbabilityClassName(value)
    : "bg-muted text-muted-foreground";

export const formatAnomalyValue = (
  value: number,
  valueType: string | null | undefined
): string =>
  isProbabilityAnomalyValue(valueType)
    ? formatAnomalyTailProbability(value)
    : formatSignal(value, 2);

export const getAnomalyValueLabel = (
  valueType: string | null | undefined
): string => {
  if (valueType === "anomaly_score") {
    return "Anomaly score";
  }
  if (valueType === "zscore") {
    return "Z-score";
  }
  if (valueType === "conformal_pvalue") {
    return "Conformal p-value";
  }
  if (valueType === "tail_pvalue") {
    return "Tail p-value";
  }
  return "Legacy score";
};

const eventTypes = new Map([
  ["ml_adaptive_stream_univariate", "Adaptive · single reading"],
  ["ml_adaptive_stream_multivariate", "Adaptive · joint readings"],
  ["ml_conformal_static_univariate", "Static · single reading"],
  ["ml_conformal_static_multivariate", "Static · joint readings"],
]);

export const formatAnomalyEventType = (type: string): string => eventTypes.get(type) ?? type;
