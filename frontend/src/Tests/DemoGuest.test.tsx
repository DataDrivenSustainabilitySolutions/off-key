import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider, useAuth } from '@/auth/AuthContext';
import { ProtectedRoute } from '@/auth/ProtectedRoute';
import { ApplicationMenu } from '@/app/ApplicationMenu';
import { SidebarFooter } from '@/app/SidebarFooter';
import { loadDemoStatus } from '@/auth/demo';
import { getCurrentMember } from '@/lib/member-api';
import { tokenManager } from '@/auth/session';

vi.mock('@/auth/demo', () => ({ loadDemoStatus: vi.fn(), isPublicDemo: () => true, DEMO_VISITOR: { name: 'Demo visitor', initials: 'DV' } }));
vi.mock('@/lib/member-api', () => ({ getCurrentMember: vi.fn() }));

const token = `test.${btoa(JSON.stringify({ user_id: 1, sub: 'admin@example.com', session_version: 0, exp: 4102444800 }))}.signature`;
const admin = { id: 1, email: 'admin@example.com', role: 'admin', permissions: ['manage_sources'] as const, is_active: true, is_verified: true, created_at: '' };

function Workspace() {
  const auth = useAuth();
  return <><p>{auth.isGuest ? 'Public workspace' : 'Admin workspace'}</p>
    {auth.can('manage_sources') && <button>Edit sources</button>}
    <button onClick={() => auth.login(token)}>Finish admin sign in</button>
    <button onClick={auth.logout}>End session</button>
    <ApplicationMenu />
    <SidebarFooter />
  </>;
}

function mount() {
  render(<AuthProvider><MemoryRouter initialEntries={['/sources']}><Routes>
    <Route path="/sources" element={<ProtectedRoute><Workspace /></ProtectedRoute>} />
    <Route path="/login" element={<p>Administrator login</p>} />
  </Routes></MemoryRouter></AuthProvider>);
}

beforeEach(() => {
  vi.resetAllMocks();
  localStorage.clear(); sessionStorage.clear(); tokenManager.removeToken();
  vi.mocked(loadDemoStatus).mockResolvedValue({ enabled: true, sources: [] });
  vi.mocked(getCurrentMember).mockResolvedValue({ ...admin, permissions: [...admin.permissions] });
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}')));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('public demo access', () => {
  it('opens the real protected workspace without a member session or write controls', async () => {
    mount();
    expect(await screen.findByText('Public workspace')).toBeTruthy();
    expect(getCurrentMember).not.toHaveBeenCalled();
    expect(tokenManager.getToken()).toBeNull();
    expect(screen.queryByRole('button', { name: 'Edit sources' })).toBeNull();
    // The sidebar shows visitors an account row like a signed-in member's.
    const [menu, account] = screen.getAllByRole('button', { name: 'Demo menu' });
    expect(account?.textContent).toBe('DVDemo visitor');
    fireEvent.pointerDown(menu!, { button: 0, ctrlKey: false, pointerType: 'mouse' });
    expect(await screen.findByText('Demo visitor · Read only')).toBeTruthy();
    fireEvent.click(screen.getByRole('menuitem', { name: 'Admin sign in' }));
    expect(await screen.findByText('Administrator login')).toBeTruthy();
  });

  it('restores normal permissions at sign in and removes them at logout', async () => {
    mount();
    await screen.findByText('Public workspace');
    fireEvent.click(screen.getByRole('button', { name: 'Finish admin sign in' }));
    expect(await screen.findByRole('button', { name: 'Edit sources' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'End session' }));
    await screen.findByText('Public workspace');
    expect(screen.queryByRole('button', { name: 'Edit sources' })).toBeNull();
  });

  it('keeps normal deployments private', async () => {
    vi.mocked(loadDemoStatus).mockResolvedValue({ enabled: false });
    mount();
    expect(await screen.findByText('Administrator login')).toBeTruthy();
    expect(screen.queryByText('Public workspace')).toBeNull();
  });

  it('keeps admin sign in reachable if public access discovery fails', async () => {
    vi.mocked(loadDemoStatus).mockRejectedValue(new Error('Offline'));
    mount();
    expect(await screen.findByRole('alert')).toBeTruthy();
    fireEvent.click(screen.getByRole('link', { name: 'Admin sign in' }));
    await waitFor(() => expect(screen.getByText('Administrator login')).toBeTruthy());
  });

  it.each([true, false])('distinguishes a Cloudflare challenge from an ordinary 403: challenge=%s', async challenge => {
    const actual = await vi.importActual<typeof import('@/auth/demo')>('@/auth/demo');
    vi.mocked(loadDemoStatus).mockImplementation(actual.loadDemoStatus);
    vi.mocked(fetch).mockResolvedValue(new Response('<html>Access check</html>', {
      status: 403, headers: challenge ? { 'cf-mitigated': 'challenge' } : {},
    }));
    mount();
    expect(await screen.findByRole('button', { name: challenge ? 'Verify browser' : 'Retry' })).toBeTruthy();
    expect(!!screen.queryByRole('link', { name: 'Admin sign in' })).toBe(!challenge);
    expect(screen.queryByText('Public workspace')).toBeNull();
  });

  it('returns to public access when a temporary discovery failure is retried', async () => {
    vi.mocked(loadDemoStatus).mockRejectedValueOnce(new Error('Offline'));
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('Public workspace')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
