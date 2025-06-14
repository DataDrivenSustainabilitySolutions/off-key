import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Login from './Login';
import { AuthProvider } from '@/auth/AuthContext';
import { vi } from 'vitest';

// Mock fetch
beforeEach(() => {
    global.fetch = vi.fn();
});
afterEach(() => {
    vi.resetAllMocks();
});

const renderLogin = () =>
    render(
        <AuthProvider>
            <MemoryRouter>
                <Login />
            </MemoryRouter>
        </AuthProvider>
    );

test('zeigt Felder und Button an', () => {
    renderLogin();
    expect(screen.getByLabelText(/E-Mail/i)).not.toBeNull();
    expect(screen.getByLabelText(/Passwort/i)).not.toBeNull();
    expect(screen.getByRole('button', { name: /einloggen/i })).toBeTruthy();
});

test('fehlerhafte Login-Daten zeigen Fehlermeldung', async () => {
    (fetch as jest.Mock).mockResolvedValueOnce({
        ok: false,
        json: async () => ({ detail: 'Test-Fehler' }),
    });

    renderLogin();
    fireEvent.change(screen.getByLabelText(/E-Mail/i), {
        target: { value: 'test@example.com' },
    });
    fireEvent.change(screen.getByLabelText(/Passwort/i), {
        target: { value: 'wrongpass' },
    });
    fireEvent.click(screen.getByRole('button', { name: /einloggen/i }));

    await waitFor(() => {
        const errorMessage = screen.queryByText(/Test-Fehler/i);
        expect(errorMessage).toBeTruthy();
    });
});

test('erfolgreicher Login zeigt Erfolg', async () => {
    const mockToken = 'abc123';
    (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ access_token: mockToken, token_type: 'bearer' }),
    });

    renderLogin();
    fireEvent.change(screen.getByLabelText(/E-Mail/i), {
        target: { value: 'test@example.com' },
    });
    fireEvent.change(screen.getByLabelText(/Passwort/i), {
        target: { value: 'correctpass' },
    });
    fireEvent.click(screen.getByRole('button', { name: /einloggen/i }));

    await waitFor(() => {
        const successMessage = screen.queryByText(/Login erfolgreich!/i);
        expect(successMessage).toBeTruthy();
    });
});
