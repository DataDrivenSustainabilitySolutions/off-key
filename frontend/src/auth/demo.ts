import { API_CONFIG, getApiUrl } from '@/lib/api-config';

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

export interface DemoStatus { enabled: boolean; sources?: DemoSource[] }
let enabled = false;
export const isPublicDemo = () => enabled;

export async function loadDemoStatus(signal: AbortSignal): Promise<DemoStatus> {
  const response = await fetch(getApiUrl('/v1/demo'), {
    signal: AbortSignal.any([signal, AbortSignal.timeout(API_CONFIG.TIMEOUT)]),
    cache: 'no-store',
  });
  // An older/private installation does not expose the capability endpoint.
  if (response.status === 404) { enabled = false; return { enabled: false }; }
  if (!response.ok) throw new Error('The demo could not be reached. Please retry.');
  const status: DemoStatus = await response.json();
  if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
  enabled = status.enabled === true;
  return { ...status, enabled };
}
