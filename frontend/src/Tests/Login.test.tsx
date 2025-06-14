import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Login from '../pages/Login';
import { AuthProvider } from '@/auth/AuthContext';
import { FetchProvider } from '../dataFetch/FetchContext';
import { vi } from 'vitest';

beforeEach(() => {
    global.fetch = vi.fn();
    localStorage.clear();
    sessionStorage.clear();
});

afterEach(() => {
    vi.resetAllMocks();
});

const renderLogin = () =>
    render(
        <AuthProvider>
            <FetchProvider>
                <MemoryRouter>
                    <Login />
                </MemoryRouter>
            </FetchProvider>
        </AuthProvider>
    );

test('zeigt Felder und Button an', () => {
    renderLogin();

    expect(screen.getByLabelText(/E-Mail/i)).toBeTruthy();
    // fix: gebe explizit an, dass es sich um ein input handeln soll
    expect(screen.getByLabelText(/Passwort/i, { selector: 'input' })).toBeTruthy();
    expect(screen.getByRole('button', { name: /log in/i })).toBeTruthy();
});

test('fehlerhafte Login-Daten zeigen Fehlermeldung', async () => {
    (fetch as any).mockResolvedValueOnce({
        ok: false,
        json: async () => ({ detail: 'Test-Fehler' }),
    });

    renderLogin();
    fireEvent.change(screen.getByLabelText(/E-Mail/i), {
        target: { value: 'test@example.com' },
    });
    fireEvent.change(screen.getByLabelText(/Passwort/i, { selector: 'input' }), {
        target: { value: 'wrongpass' },
    });
    fireEvent.click(screen.getByRole('button', { name: /log in/i }));

    await waitFor(() => {
        expect(screen.queryByText(/Test-Fehler/i)).not.toBeNull();
    });
});

test('erfolgreicher Login speichert Token und navigiert', async () => {
    const mockToken = 'abc123';

    (fetch as any).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ access_token: mockToken, token_type: 'bearer' }),
    });

    renderLogin();
    fireEvent.change(screen.getByLabelText(/E-Mail/i), {
        target: { value: 'test@example.com' },
    });
    fireEvent.change(screen.getByLabelText(/Passwort/i, { selector: 'input' }), {
        target: { value: 'correctpass' },
    });
    fireEvent.click(screen.getByRole('button', { name: /log in/i }));

    await waitFor(() => {
        const token = sessionStorage.getItem('token') || localStorage.getItem('token');
        expect(token).toBe(mockToken);
    });
});
