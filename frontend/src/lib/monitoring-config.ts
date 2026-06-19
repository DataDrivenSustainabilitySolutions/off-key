export const parseNumericInput = (
  rawValue: string,
  schemaType?: string
): string | number => {
  const trimmed = rawValue.trim();
  if (trimmed === "") return "";

  if (schemaType === "integer" || schemaType === "number") {
    const parsed = Number(trimmed);
    if (!Number.isFinite(parsed)) return "";
    return schemaType === "integer" && !Number.isInteger(parsed) ? "" : parsed;
  }

  return rawValue;
};
