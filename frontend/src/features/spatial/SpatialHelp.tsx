import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  configuredSystem?: boolean;
};

export function SpatialHelp({
  open,
  onOpenChange,
  configuredSystem = false,
}: Props) {
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
            <dt>Automatic layout</dt>
            <dd>
              Objects are placed automatically from the system structure. Use
              groups and search to focus on what matters.
            </dd>
            <dt>Keyboard</dt>
            <dd>
              {configuredSystem
                ? "Click a title to rename it. Enter or clicking elsewhere saves; Escape cancels."
                : "F focuses the selected object. Escape closes the selection."}
            </dd>
            {configuredSystem && (
              <>
                <dt>Connect</dt>
                <dd>
                  Connect listens to the saved MQTT topics. Select a stream
                  for real values and its recent chart. Pulses sample fresh
                  arrivals; counters include every delivery. Preview data stays
                  in memory. Disconnect, edit the saved system, or leave the tab
                  to release the connection. Members can view an administrator's
                  active preview.
                </dd>
              </>
            )}
            <dt>Keep your place</dt>
            <dd>
              Camera and groups save automatically on this browser. Save named
              perspectives in preferences.
            </dd>
            <dt>Performance</dt>
            <dd>
              {configuredSystem
                ? "The scene renders on demand while idle. Economy caps resolution and frame rate. Hidden tabs stop rendering."
                : "Try 250 or 1,000 streams in preferences. Economy caps resolution and frame rate. Hidden tabs stop rendering."}
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
