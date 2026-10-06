import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";

type Props = { open: boolean; onOpenChange: (open: boolean) => void };

export function SpatialHelp({ open, onOpenChange }: Props) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Overlay className="sp-help-backdrop">
        <Dialog.Content aria-describedby={undefined} className="sp-help">
          <button
            className="sp-help-close"
            onClick={() => onOpenChange(false)}
            aria-label="Close help"
          >
            <X size={18} />
          </button>
          <span className="sp-overline">A little orientation</span>
          <Dialog.Title asChild>
            <h2>Your system, in perspective.</h2>
          </Dialog.Title>
          <dl>
            <dt>Select</dt>
            <dd>Click an object or use the searchable object list.</dd>
            <dt>Navigate</dt>
            <dd>
              Scroll to zoom. Drag empty space to pan; right-drag to orbit.
            </dd>
            <dt>Arrange</dt>
            <dd>Enable Arrange, then drag objects or collection tiles.</dd>
            <dt>Pin</dt>
            <dd>
              Pin objects or lock a whole collection to preserve its placement.
            </dd>
            <dt>Keyboard</dt>
            <dd>
              Arrow keys move selected objects. Shift moves further. F focuses.
              Escape closes. ⌘/Ctrl Z undoes.
            </dd>
            <dt>Keep your place</dt>
            <dd>
              Camera, layout, groups, and locks save automatically. Save named
              perspectives in preferences.
            </dd>
            <dt>Performance</dt>
            <dd>
              Try 250 or 1,000 streams in preferences. Economy caps resolution
              and frame rate. Hidden tabs stop rendering.
            </dd>
          </dl>
          <button
            className="sp-primary-button"
            onClick={() => onOpenChange(false)}
          >
            Let's explore
          </button>
        </Dialog.Content>
      </Dialog.Overlay>
    </Dialog.Root>
  );
}
