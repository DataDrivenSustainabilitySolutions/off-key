import * as Popover from "@radix-ui/react-popover";
import { Keyboard, X } from "lucide-react";
import { SHORTCUT_SHEET, SHORTCUTS } from "./shortcuts";

/** The keys and gestures of the canvas, listed on demand from a button beside its zoom buttons. */
export function PipelineShortcuts({ open, onOpenChange, readOnly }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** A design that is only shown lists what can be done with it. */
  readOnly?: boolean;
}) {
  const groups = SHORTCUT_SHEET
    .map((group) => ({ ...group, rows: group.rows.filter((row) => !readOnly || !row.edits) }))
    .filter((group) => group.rows.length);
  return <Popover.Root open={open} onOpenChange={onOpenChange}>
    <Popover.Trigger className="react-flow__controls-button" aria-label="Keyboard shortcuts"
      title={`Keyboard shortcuts (${SHORTCUTS.help.label})`}>
      <Keyboard size={16} aria-hidden="true" />
    </Popover.Trigger>
    <Popover.Portal>
      <Popover.Content className="pl-library pl-shortcuts" side="top" align="start" sideOffset={10} collisionPadding={12}
        aria-label="Keyboard shortcuts">
        <div className="pl-component-menu-heading"><h3>Keyboard shortcuts</h3>
          <Popover.Close aria-label="Close keyboard shortcuts"><X size={16} aria-hidden="true" /></Popover.Close>
        </div>
        <div className="pl-shortcut-groups">
          {groups.map((group) => <section key={group.title}>
            <h4>{group.title}</h4>
            <dl>{group.rows.map((row) => <div key={row.does}>
              <dt>{row.does}</dt>
              <dd>{row.keys.map((keys) => <kbd key={keys}>{keys}</kbd>)}</dd>
            </div>)}</dl>
          </section>)}
        </div>
        <p className="pl-help">Letter and number keys work while the canvas is in focus: click it, or move into it with Tab.</p>
      </Popover.Content>
    </Popover.Portal>
  </Popover.Root>;
}
