import { useRef, useState } from "react";
import { Pencil } from "lucide-react";
import { cn } from "@/lib/utils";

export const fieldClass =
  "rounded-md border bg-background px-3 py-2 text-sm w-full min-w-0";

export function InlineField({
  label,
  value,
  onChange,
  disabled,
  type = "text",
  min,
  max,
  maxLength,
  placeholder = "Not set",
  optional = false,
  className,
  onCancel,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
  type?: "text" | "number";
  min?: number;
  max?: number;
  maxLength?: number;
  placeholder?: string;
  optional?: boolean;
  className?: string;
  onCancel?: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const initial = useRef(value);
  const cancel = useRef(onCancel);
  const trigger = useRef<HTMLButtonElement>(null);
  const finish = () => {
    setEditing(false);
    requestAnimationFrame(() => trigger.current?.focus());
  };

  return (
    <div className={cn("min-w-0", className)}>
      {editing && !disabled ? (
        <input
          autoFocus
          aria-label={label}
          className={fieldClass}
          type={type}
          min={min}
          max={max}
          step={type === "number" ? 1 : undefined}
          maxLength={maxLength}
          required={!optional}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onBlur={() => setEditing(false)}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              event.stopPropagation();
              if (cancel.current) cancel.current();
              else onChange(initial.current);
              finish();
            } else if (event.key === "Enter") {
              event.preventDefault();
              if (event.currentTarget.reportValidity()) finish();
            }
          }}
        />
      ) : (
        <button
          ref={trigger}
          type="button"
          disabled={disabled}
          aria-label={`${disabled ? "View" : "Edit"} ${label}: ${value || placeholder}`}
          className="group inline-flex min-h-9 max-w-full items-center gap-2 rounded-md px-2 py-1 text-left hover:enabled:bg-muted focus-visible:outline-2 focus-visible:outline-ring disabled:cursor-default"
          onClick={() => {
            initial.current = value;
            cancel.current = onCancel;
            setEditing(true);
          }}
        >
          <span
            className={cn(
              "min-w-0 break-words",
              !value && "text-muted-foreground",
            )}
          >
            {value || placeholder}
          </span>
          {!disabled && (
            <Pencil
              aria-hidden="true"
              className="size-3 shrink-0 text-muted-foreground opacity-50 sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-visible:opacity-100"
            />
          )}
        </button>
      )}
    </div>
  );
}
