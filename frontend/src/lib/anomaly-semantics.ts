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

export const formatAnomalyTailProbability = (tailProbability: number): string =>
  tailProbability.toFixed(4);

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
    : value.toFixed(2);

export const getAnomalyValueLabel = (
  valueType: string | null | undefined
): string => {
  if (valueType === "conformal_pvalue") {
    return "Conformal p-value";
  }
  if (valueType === "tail_pvalue") {
    return "Tail p-value";
  }
  return "Legacy score";
};
