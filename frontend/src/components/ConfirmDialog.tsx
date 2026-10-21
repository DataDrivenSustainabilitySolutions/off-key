import { useRef, type ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Button } from "@/components/ui/button";

export type ConfirmOptions = {
  title: string;
  description?: ReactNode;
  confirmLabel: string;
  busyLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
};

type Props = ConfirmOptions & {
  open: boolean;
  busy?: boolean;
  error?: string;
  onConfirm: () => void;
  onCancel: () => void;
  onCloseAutoFocus?: (event: Event) => void;
};

/** The application's one confirmation: Cancel first and focused, the action on the right. */
export function ConfirmDialog({ open, title, description, confirmLabel, busyLabel, cancelLabel = "Cancel", destructive = false,
  busy = false, error, onConfirm, onCancel, onCloseAutoFocus }: Props) {
  const cancel = useRef<HTMLButtonElement>(null);
  return <Dialog.Root open={open} onOpenChange={next => { if (!next && !busy) onCancel(); }}>
    <Dialog.Portal><Dialog.Overlay className="ex-dialog-overlay" />
      <Dialog.Content className="ex-dialog ex-confirm" onCloseAutoFocus={onCloseAutoFocus}
        onOpenAutoFocus={event => { event.preventDefault(); cancel.current?.focus(); }}
        onEscapeKeyDown={event => { if (busy) event.preventDefault(); }}
        onPointerDownOutside={event => { if (busy) event.preventDefault(); }}>
        <Dialog.Title>{title}</Dialog.Title>
        {description ? <Dialog.Description className="ex-confirm-description">{description}</Dialog.Description>
          : <Dialog.Description className="ex-sr-only">{title}</Dialog.Description>}
        {error && <p className="ex-preview-error" role="alert">{error}</p>}
        <div className="ex-dialog-actions">
          <Button ref={cancel} variant="outline" disabled={busy} onClick={onCancel}>{cancelLabel}</Button>
          <Button variant={destructive ? "destructive" : "default"} disabled={busy} onClick={onConfirm}>{busy ? busyLabel ?? confirmLabel : confirmLabel}</Button>
        </div>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
