export const getAnomalyTailProbabilityClassName = (
  tailProbability: number
): string => {
  if (tailProbability <= 0.001) {
    return "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200";
  }
  if (tailProbability <= 0.005) {
    return "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200";
  }
  return "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200";
};

export const formatAnomalyTailProbability = (tailProbability: number): string =>
  tailProbability.toFixed(4);
