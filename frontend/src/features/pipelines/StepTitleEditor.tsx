import { useRef } from "react";

/** A step title typed in place: Enter or leaving keeps it, Escape keeps the old one. */
export function StepTitleEditor({ title, operation, className, onFinish }: {
  title: string;
  /** The step's own name, shown while the title is empty. */
  operation: string;
  className?: string;
  /** Called once, with the title to keep or with nothing when Escape cancels. */
  onFinish: (title?: string) => void;
}) {
  const done = useRef(false);
  const end = (value?: string) => {
    if (done.current) return;
    done.current = true;
    onFinish(value);
  };
  return <input
    className={className}
    aria-label="Step title"
    maxLength={120}
    defaultValue={title}
    placeholder={operation}
    ref={(element) => { if (element && document.activeElement !== element) { element.focus({ preventScroll: true }); element.select(); } }}
    onKeyDown={(event) => {
      // Keys belong to the title: Backspace must not delete the card, nor Ctrl+Z undo the graph.
      event.stopPropagation();
      if (event.key === "Enter") { event.preventDefault(); end(event.currentTarget.value); }
      else if (event.key === "Escape") { event.preventDefault(); end(); }
    }}
    onBlur={(event) => end(event.currentTarget.value)}
    onClick={(event) => event.stopPropagation()}
    onDoubleClick={(event) => event.stopPropagation()}
  />;
}
