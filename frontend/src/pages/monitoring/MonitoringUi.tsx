import { cn } from "@/lib/utils";
import { CheckCircle2 } from "lucide-react";
import type { ElementType } from "react";

export function LaneCard({ title, description, selected = false, icon: Icon, onSelect }: {
  title: string;
  description?: string;
  selected?: boolean;
  icon: ElementType;
  onSelect?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "rounded-md border px-3 py-2.5 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        selected ? "border-primary/40 bg-accent" : "border-border bg-card hover:bg-accent/60",
      )}
      aria-pressed={selected}
    >
      <span className="flex items-center gap-2 font-medium">
        <Icon className="size-4 text-primary" aria-hidden="true" />
        {title}
        {selected && <CheckCircle2 className="ml-auto size-4 text-primary" aria-hidden="true" />}
      </span>
      {description && <span className="mt-1 block text-sm text-muted-foreground">{description}</span>}
    </button>
  );
}
