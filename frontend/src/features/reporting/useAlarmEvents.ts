import { useCallback, useEffect, useRef, useState } from 'react';
import { queryAlarms } from '@/lib/charger-api';
import { getErrorMessage } from '@/lib/errors';
import type { AlarmPage, AlarmQuery } from '@/types/charger';

type Result = { key: string; query: AlarmQuery; page: AlarmPage; updatedAt: string };

/** Every load, including manual refreshes, belongs to one cancellable query. */
export function useAlarmEvents(query: AlarmQuery, windowMs?: number) {
  const key = JSON.stringify([query, windowMs]);
  const [result, setResult] = useState<Result>();
  const [failure, setFailure] = useState<{ key: string; message: string }>();
  const [busy, setBusy] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const pending = useRef<AbortController | undefined>(undefined);
  const current = useRef(result);
  useEffect(() => { current.current = result; }, [result]);

  const load = useCallback(async (retainCount = false) => {
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    const [base, span] = JSON.parse(key) as [AlarmQuery, number | null];
    const sent = { ...base, ...(span != null && { since: new Date(Date.now() - span).toISOString() }) };
    const targetCount = retainCount && current.current?.key === key ? current.current.page.items.length : 0;
    setBusy(true); setFailure(undefined); setLoadingOlder(false);
    try {
      let page = await queryAlarms(sent, controller.signal);
      while (page.next && page.items.length < targetCount && !controller.signal.aborted) {
        const older = await queryAlarms({ ...sent, before: page.next }, controller.signal);
        page = { ...older, items: [...page.items, ...older.items] };
      }
      if (!controller.signal.aborted) setResult({ key, query: sent, page, updatedAt: new Date().toISOString() });
    } catch (error) {
      if (!controller.signal.aborted) setFailure({ key, message: getErrorMessage(error) });
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }, [key]);

  useEffect(() => {
    const timer = window.setTimeout(() => { void load(); }, 0);
    return () => { window.clearTimeout(timer); pending.current?.abort(); };
  }, [load]);

  const loadOlder = async () => {
    const previous = current.current;
    if (!previous?.page.next || previous.key !== key || busy || loadingOlder) return;
    const controller = new AbortController();
    pending.current?.abort(); pending.current = controller;
    setLoadingOlder(true); setFailure(undefined);
    try {
      const page = await queryAlarms({ ...previous.query, before: previous.page.next }, controller.signal);
      if (!controller.signal.aborted) setResult(value => value === previous
        ? { ...previous, page: { ...page, items: [...previous.page.items, ...page.items] } } : value);
    } catch (error) {
      if (!controller.signal.aborted) setFailure({ key, message: getErrorMessage(error) });
    } finally {
      if (!controller.signal.aborted) setLoadingOlder(false);
    }
  };
  return { key, result: result?.key === key ? result : undefined,
    error: failure?.key === key ? failure.message : undefined,
    busy: busy || (result?.key !== key && failure?.key !== key), loadingOlder, load, loadOlder };
}
