import { useState } from 'react';
import toast from 'react-hot-toast';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { previewAlarmDeletion, deleteAlarmSelection } from '@/lib/charger-api';
import { getErrorMessage } from '@/lib/errors';
import type { AlarmDeletionPreview, AlarmSelection } from '@/types/charger';

export function useAlarmDeletion(onDeleted: () => Promise<void>) {
  const [request, setRequest] = useState<{ preview: AlarmDeletionPreview; description: string }>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const prepare = async (selection: AlarmSelection, description: string) => {
    if (busy || request) return;
    setBusy(true); setError('');
    try {
      const preview = await previewAlarmDeletion(selection);
      if (preview.count === 0) { toast('These anomalies are already gone.'); await onDeleted(); }
      else setRequest({ preview, description });
    } catch (error) { toast.error(`Selection could not be prepared: ${getErrorMessage(error)}`); }
    finally { setBusy(false); }
  };
  const commit = async () => {
    if (!request || busy) return;
    setBusy(true); setError('');
    try {
      const result = await deleteAlarmSelection(request.preview.token);
      setRequest(undefined);
      toast.success(`${result.count.toLocaleString()} ${result.count === 1 ? 'anomaly' : 'anomalies'} deleted`);
      await onDeleted();
    } catch (error) { setError(getErrorMessage(error)); }
    finally { setBusy(false); }
  };
  const count = request?.preview.count ?? 0;
  return { prepare, busy, pending: !!request, confirmation: request && <ConfirmDialog open
    title={count === 1 ? 'Delete this anomaly?' : `Delete ${count.toLocaleString()} anomalies?`}
    description={<>{request.description} Only the {count.toLocaleString()} reviewed {count === 1 ? 'record' : 'records'} will be deleted.
      {' '}New arrivals are excluded. This cannot be undone.</>}
    confirmLabel={count === 1 ? 'Delete anomaly' : `Delete ${count.toLocaleString()} anomalies`}
    busyLabel="Deleting…" destructive busy={busy} error={error}
    onConfirm={() => void commit()} onCancel={() => { setRequest(undefined); setError(''); }} /> };
}
