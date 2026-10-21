import { useState } from "react";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { getErrorMessage } from "@/lib/errors";
import { removeMember, type Member } from "@/lib/member-api";

type Props = {
  member: Member;
  onClose: () => void;
  onRemoved: () => void;
  onCloseAutoFocus: (event: Event) => void;
};

export function RemoveMemberDialog({ member, onClose, onRemoved, onCloseAutoFocus }: Props) {
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
    <ConfirmDialog open title="Remove member?" confirmLabel="Remove member" busyLabel="Removing…" destructive busy={busy} error={error}
      description={<>
        Permanently remove <strong>{member.email}</strong> and their personal favorites.
        {" "}They will need a new invitation to join again. Shared catalogue data, monitoring services, and reports are kept.
      </>}
      onConfirm={() => void remove()} onCancel={onClose} onCloseAutoFocus={onCloseAutoFocus} />
  );
}
