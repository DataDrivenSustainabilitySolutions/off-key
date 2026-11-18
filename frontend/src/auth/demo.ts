import { API_CONFIG, getApiUrl } from '@/lib/api-config';
import { browserVerificationRequired } from '@/lib/browser-verification';

interface DemoSource {
  id: string;
  name: string;
  url: string;
  attribution: string;
  license: string;
  license_url: string;
  simulated: boolean;
  note: string;
}

/** Public demo visitors appear as a signed-in, read-only account. */
export const DEMO_VISITOR = { name: 'Demo visitor', initials: 'DV' } as const;

export interface DemoStatus { enabled: boolean; sources?: DemoSource[] }

export async function loadDemoStatus(signal: AbortSignal): Promise<DemoStatus> {
  const response = await fetch(getApiUrl('/v1/demo'), {
    signal: AbortSignal.any([signal, AbortSignal.timeout(API_CONFIG.TIMEOUT)]),
    cache: 'no-store',
  });
  if (response.headers.get('cf-mitigated') === 'challenge') throw browserVerificationRequired();
  // An older/private installation does not expose the capability endpoint.
  if (response.status === 404) return { enabled: false };
  if (!response.ok) throw new Error('The demo could not be reached. Please retry.');
  const status: DemoStatus = await response.json();
  if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
  return { ...status, enabled: status.enabled === true };
}
