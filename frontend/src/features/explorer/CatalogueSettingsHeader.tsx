import * as Dialog from "@radix-ui/react-dialog";
import { SlidersHorizontal, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import "./catalogue-settings.css";

export function CatalogueSettingsHeader({ disabled }: { disabled: boolean }) {
  return <header className="catalogue-settings-heading">
    <span className="catalogue-settings-heading-icon"><SlidersHorizontal size={20} aria-hidden="true" /></span>
    <div className="catalogue-settings-heading-copy">
      <Dialog.Title>Catalogue settings</Dialog.Title>
      <Dialog.Description>Manage your sources and catalogue files.</Dialog.Description>
    </div>
    <Dialog.Close asChild>
      <Button type="button" variant="ghost" size="icon" disabled={disabled} aria-label="Close settings"><X aria-hidden="true" /></Button>
    </Dialog.Close>
  </header>;
}
