import { useRef, type ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";

type Props = {
  open: boolean;
  title: string;
  description?: ReactNode;
  submitLabel: string;
  busyLabel?: string;
  cancelLabel?: string;
  busy?: boolean;
  error?: string;
  onSubmit: () => void;
  onClose: () => void;
  children: ReactNode;
};

/**
 * The application's one dialog for adding or editing something: a title, the
 * fields, then Cancel and the action on the right. It opens on its first field
 * and returns focus to what opened it.
 */
export function FormDialog({ open, title, description, submitLabel, busyLabel, cancelLabel = "Cancel",
  busy = false, error, onSubmit, onClose, children }: Props) {
  const form = useRef<HTMLFormElement>(null);
  const origin = useRef<HTMLElement | null>(null);
  return <Dialog.Root open={open} onOpenChange={next => { if (!next && !busy) onClose(); }}>
    <Dialog.Portal><Dialog.Overlay className="ex-dialog-overlay" />
      <Dialog.Content className="ex-dialog ex-form-dialog"
        onOpenAutoFocus={event => {
          origin.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
          const field = form.current?.querySelector<HTMLElement>("input, select, textarea");
          if (!field) return;
          event.preventDefault();
          field.focus();
        }}
        onCloseAutoFocus={event => {
          if (!origin.current?.isConnected) return;
          event.preventDefault();
          origin.current.focus();
        }}
        onEscapeKeyDown={event => { if (busy) event.preventDefault(); }}
        onPointerDownOutside={event => { if (busy) event.preventDefault(); }}>
        <header><Dialog.Title>{title}</Dialog.Title>
          <Dialog.Close className="ex-icon-button" disabled={busy} aria-label="Close"><X size={18} aria-hidden="true" /></Dialog.Close></header>
        {description ? <Dialog.Description className="ex-form-dialog-description">{description}</Dialog.Description>
          : <Dialog.Description className="ex-sr-only">{title}</Dialog.Description>}
        <form ref={form} aria-label={title} onSubmit={event => { event.preventDefault(); if (!busy) onSubmit(); }}>
          {children}
          {error && <p className="ex-preview-error" role="alert">{error}</p>}
          <div className="ex-dialog-actions">
            <Button type="button" variant="outline" disabled={busy} onClick={onClose}>{cancelLabel}</Button>
            <Button type="submit" disabled={busy}>{busy ? busyLabel ?? submitLabel : submitLabel}</Button>
          </div>
        </form>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
