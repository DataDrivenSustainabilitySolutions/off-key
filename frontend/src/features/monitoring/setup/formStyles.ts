export const CONTROL_CLASS =
  "h-10 w-full rounded-lg border border-input bg-card px-3 py-2 text-sm shadow-xs outline-none transition-[border-color,box-shadow] focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/25 aria-invalid:border-destructive";
export const LABEL_CLASS = "text-sm font-medium text-foreground";
export const HELP_CLASS = "mt-1 text-xs leading-5 text-muted-foreground";
export const ERROR_CLASS = "mt-1 text-xs leading-5 text-destructive";

export const errorId = (field: string) =>
  `monitoring-${field.replace(/[^a-zA-Z0-9_-]/g, "-")}-error`;
