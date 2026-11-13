import * as Dialog from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { useAuth } from '@/auth/AuthContext';

/** Provider attribution stays available wherever a visitor explores the app. */
export function DemoSources({ open, onOpenChange, returnFocus }: { open: boolean; onOpenChange: (open: boolean) => void; returnFocus: () => void }) {
  const { isGuest, demo } = useAuth();
  if (!isGuest || !demo?.sources?.length) return null;
  return <Dialog.Root open={open} onOpenChange={onOpenChange}>
    <Dialog.Portal>
      <Dialog.Overlay className="app-settings-overlay" style={{ zIndex: 100 }} />
      <Dialog.Content style={{ zIndex: 101 }} onCloseAutoFocus={event => { event.preventDefault(); returnFocus(); }} className="fixed left-1/2 top-1/2 max-h-[85vh] w-[min(38rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-xl border border-border bg-background p-6 shadow-xl">
        <Dialog.Title className="text-lg font-semibold">Demo data sources</Dialog.Title>
        <Dialog.Description className="mt-2 text-sm text-muted-foreground">
          Selected public MQTT feeds, processed by the same collection and monitoring tools as any installation. Charts show when measurements arrived. A quiet or unavailable feed keeps its last recorded history.
        </Dialog.Description>
        <ul className="mt-5 space-y-4">{demo.sources.map(source => <li key={source.id} className="border-t border-border pt-3 text-sm">
          <a href={source.url} target="_blank" rel="noreferrer" className="font-medium underline underline-offset-4">{source.name}</a>
          {source.simulated && <span className="ml-2 text-xs text-muted-foreground">Simulated</span>}
          <p className="mt-1 text-muted-foreground">{source.attribution} · <a href={source.license_url} target="_blank" rel="noreferrer" className="underline">{source.license}</a></p>
          {source.note && <p className="mt-1 text-muted-foreground">{source.note}</p>}
        </li>)}</ul>
        <Dialog.Close className="absolute right-4 top-4 text-muted-foreground" aria-label="Close data sources"><X size={18} /></Dialog.Close>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
