import { useId } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Palette, X } from "lucide-react";
import { AppearanceSettings } from "./AppearanceSettings";
import "./settings.css";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCloseAutoFocus: (event: Event) => void;
};

export function SettingsDialog({ open, onOpenChange, onCloseAutoFocus }: Props) {
  const id = useId();

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="app-settings-overlay" />
        <Dialog.Content className="app-settings-dialog" onCloseAutoFocus={onCloseAutoFocus}>
          <aside className="app-settings-sidebar">
            <Dialog.Title className="app-settings-title">Settings</Dialog.Title>
            <div role="tablist" aria-label="Settings categories" className="app-settings-categories">
              <button type="button" role="tab" id={`${id}-appearance-tab`}
                aria-selected="true" aria-controls={`${id}-appearance-panel`}>
                <Palette size={17} aria-hidden="true" />Appearance
              </button>
            </div>
          </aside>
          <section className="app-settings-content" role="tabpanel"
            id={`${id}-appearance-panel`} aria-labelledby={`${id}-appearance-tab`}>
            <div className="app-settings-heading">
              <h2>Appearance</h2>
              <Dialog.Description>Choose how Aberration looks on this device.</Dialog.Description>
            </div>
            <AppearanceSettings />
          </section>
          <Dialog.Close className="app-settings-close" aria-label="Close settings" title="Close settings">
            <X size={18} aria-hidden="true" />
          </Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
