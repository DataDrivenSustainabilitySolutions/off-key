import { useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Button } from "@/components/ui/button";
import { getErrorMessage } from "@/lib/errors";
import { removeMember, type Member } from "@/lib/member-api";

type Props = {
  member: Member;
  onClose: () => void;
  onRemoved: () => void;
  onCloseAutoFocus: (event: Event) => void;
};

export function RemoveMemberDialog({ member, onClose, onRemoved, onCloseAutoFocus }: Props) {
  const cancel = useRef<HTMLButtonElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const remove = async () => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await removeMember(member.id);
      onRemoved();
    } catch (error) {
      setError(getErrorMessage(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog.Root open onOpenChange={(open) => { if (!open && !busy) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/50" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-50 grid max-h-[calc(100dvh_-_2rem)] w-[calc(100%_-_2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 gap-5 overflow-y-auto rounded-xl border bg-card p-6 text-card-foreground shadow-xl"
          onOpenAutoFocus={(event) => { event.preventDefault(); cancel.current?.focus(); }}
          onCloseAutoFocus={onCloseAutoFocus}
          onEscapeKeyDown={(event) => { if (busy) event.preventDefault(); }}
          onPointerDownOutside={(event) => { if (busy) event.preventDefault(); }}
        >
          <Dialog.Title className="text-lg font-medium">Remove member?</Dialog.Title>
          <Dialog.Description className="break-words text-sm leading-6 text-muted-foreground">
            Permanently remove <strong className="font-medium text-foreground">{member.email}</strong> and their personal favorites.
            {" "}They will need a new invitation to join again. Shared catalogue data, monitoring services, and reports are kept.
          </Dialog.Description>
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
          <div className="flex flex-wrap justify-end gap-2">
            <Button ref={cancel} variant="outline" disabled={busy} onClick={onClose}>Cancel</Button>
            <Button variant="destructive" disabled={busy} onClick={() => void remove()}>
              {busy ? "Removing…" : "Remove member"}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
