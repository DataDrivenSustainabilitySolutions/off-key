import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Login from '../pages/Login';
import { AuthProvider } from '@/auth/AuthContext';
import { FetchProvider } from '../dataFetch/FetchContext';
import { vi } from 'vitest';

let fetchMock: ReturnType<typeof vi.fn>;
let originalFetch: typeof global.fetch;

beforeEach(() => {
    originalFetch = global.fetch;
    fetchMock = vi.fn();
    global.fetch = fetchMock as typeof fetch;
    localStorage.clear();
    sessionStorage.clear();
});

afterEach(() => {
    global.fetch = originalFetch;
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
    fetchMock.mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: 'Test-Fehler' }), {
            status: 401,
            headers: { 'Content-Type': 'application/json' },
        })
    );

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

    fetchMock.mockResolvedValueOnce(
        new Response(
            JSON.stringify({ access_token: mockToken, token_type: 'bearer' }),
            {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            }
        )
    );

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
