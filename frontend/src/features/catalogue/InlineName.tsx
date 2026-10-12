import { useEffect, useId, useRef, useState } from "react";

type Props = {
  value: string;
  onSave: (name: string) => Promise<void>;
  editable?: boolean;
  disabledReason?: string;
  ariaLabel?: string;
  className?: string;
  saveError?: string;
};
const SAVE_FAILURE =
  "Could not save the name. Try again or press Escape to cancel.";

/** Titles edit in place; the caller owns persistence and only updates value after success. */
export function InlineName({
  value,
  onSave,
  editable = true,
  disabledReason,
  ariaLabel = "Rename title",
  className,
  saveError,
}: Props) {
  const descriptionId = useId();
  const input = useRef<HTMLInputElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const active = useRef(false);
  const saving = useRef(false);
  const selectText = useRef(false);
  const restoreFocus = useRef(false);
  const [originalName, setOriginalName] = useState(value);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    if (editing && editable && !pending) {
      input.current?.focus();
      if (selectText.current) {
        input.current?.select();
        selectText.current = false;
      }
    } else if (!editing && restoreFocus.current) {
      trigger.current?.focus();
      restoreFocus.current = false;
    }
  }, [editing, editable, pending]);

  const begin = () => {
    if (!editable || saving.current) return;
    active.current = true;
    setOriginalName(value);
    selectText.current = true;
    setDraft(value);
    setError("");
    setStatus("");
    setEditing(true);
  };

  const cancel = () => {
    if (saving.current) return;
    active.current = false;
    restoreFocus.current = true;
    setEditing(false);
    setError("");
    setStatus("");
  };

  const commit = async (keyboard: boolean) => {
    if (!editable || !active.current || saving.current) return;
    const name = draft.trim();
    if (!name) {
      setError("Enter a name.");
      return;
    }
    if (name.length > 120) {
      setError("Use 120 characters or fewer.");
      return;
    }
    if (name === value) {
      active.current = false;
      restoreFocus.current = keyboard;
      setEditing(false);
      setError("");
      return;
    }
    // Enter can blur the input while the save starts. Guard synchronously before awaiting.
    saving.current = true;
    setPending(true);
    setError("");
    setStatus("Saving…");
    try {
      await onSave(name);
      active.current = false;
      restoreFocus.current = keyboard;
      setEditing(false);
      setStatus("");
    } catch {
      setStatus("");
      setError(SAVE_FAILURE);
    } finally {
      saving.current = false;
      setPending(false);
    }
  };

  const isEditing = editing && editable;
  const saveFailed = error === SAVE_FAILURE;
  const errorMessage = saveFailed ? saveError || error : error;
  const description =
    errorMessage ||
    (isEditing ? status : editable ? status : disabledReason || status);
  return (
    <span className={`sp-inline-name${className ? ` ${className}` : ""}`}>
      {isEditing ? (
        <input
          ref={input}
          className="sp-inline-name-input"
          aria-label={ariaLabel}
          aria-describedby={description ? descriptionId : undefined}
          aria-invalid={!!error}
          aria-busy={pending}
          maxLength={120}
          value={draft}
          disabled={pending}
          onChange={(event) => {
            setDraft(event.target.value);
            setError("");
          }}
          onBlur={() => void commit(false)}
          onKeyDown={(event) => {
            if (event.nativeEvent.isComposing) return;
            if (event.key === "Enter") {
              event.preventDefault();
              event.stopPropagation();
              void commit(true);
            } else if (event.key === "Escape") {
              event.preventDefault();
              event.stopPropagation();
              cancel();
            }
          }}
        />
      ) : (
        <button
          ref={trigger}
          type="button"
          className="sp-inline-name-trigger"
          aria-label={ariaLabel}
          aria-describedby={description ? descriptionId : undefined}
          disabled={!editable}
          title={editable ? "Click to rename" : disabledReason}
          onClick={begin}
        >
          {value}
        </button>
      )}
      {description && (
        <span
          id={descriptionId}
          className={error ? "sp-inline-name-error" : "sp-inline-name-status"}
          role={error ? "alert" : editable ? "status" : undefined}
        >
          {description}
          {saveFailed && value !== originalName && (
            <span className="sp-inline-name-current">
              Current saved name: {value}
            </span>
          )}
        </span>
      )}
    </span>
  );
}
