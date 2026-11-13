export const CONTROL_CLASS =
  "min-h-11 w-full rounded-md border border-input bg-card px-3 py-2 text-sm outline-none transition-[border-color,box-shadow] md:min-h-10 focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background aria-invalid:border-destructive";
export const LABEL_CLASS = "text-sm font-medium text-foreground";
export const HELP_CLASS = "mt-1 text-xs leading-5 text-muted-foreground";
export const ERROR_CLASS = "mt-1 text-xs leading-5 text-destructive";

export const errorId = (field: string) =>
  `monitoring-${field.replace(/[^a-zA-Z0-9_-]/g, "-")}-error`;
