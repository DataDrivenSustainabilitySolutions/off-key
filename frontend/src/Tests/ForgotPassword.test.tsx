import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import ForgotPassword from '../pages/ForgotPassword';
import { vi } from 'vitest';
import { API_CONFIG, getApiUrl } from '@/lib/api-config';

// @ts-expect-error: TS kennt global.fetch nicht
global.fetch = vi.fn();

describe('ForgotPassword', () => {
    beforeEach(() => {
        vi.resetAllMocks();
        vi.spyOn(console, 'error').mockImplementation(() => undefined);
    });

    test('zeigt Eingabefeld und Button', () => {
        render(<ForgotPassword />);
        expect(screen.getByLabelText(/E-Mail/i)).toBeDefined();
        expect(screen.getByRole('button', { name: /Reset Password/i })).toBeDefined();
    });

    test('erlaubt Eingabe in das E-Mail-Feld', () => {
        render(<ForgotPassword />);
        const input = screen.getByLabelText(/E-Mail/i);
        fireEvent.change(input, { target: { value: 'test@example.com' } });
        expect((input as HTMLInputElement).value).toBe('test@example.com');
    });

    test('zeigt Erfolgsmeldung nach Submit', async () => {
        (fetch as unknown as vi.Mock).mockResolvedValueOnce({
            ok: true,
            json: async () => ({ message: 'Reset link gesendet!' }),
        });

        render(<ForgotPassword />);
        const input = screen.getByLabelText(/E-Mail/i);
        const button = screen.getByRole('button', { name: /Reset Password/i });

        fireEvent.change(input, { target: { value: 'test@example.com' } });
        fireEvent.click(button);

        await waitFor(() => {
            expect(screen.getByText(/Reset link gesendet!/i)).toBeDefined();
        });

        expect(fetch).toHaveBeenCalledWith(
            getApiUrl(API_CONFIG.ENDPOINTS.AUTH.FORGOT_PASSWORD),
            expect.objectContaining({
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: 'test@example.com' }),
            })
        );
    });

    test('zeigt Fehlermeldung bei fetch-Fehler', async () => {
        (fetch as unknown as vi.Mock).mockRejectedValueOnce(new Error('Failed'));

        render(<ForgotPassword />);
        const input = screen.getByLabelText(/E-Mail/i);
        const button = screen.getByRole('button', { name: /Reset Password/i });

        fireEvent.change(input, { target: { value: 'fail@example.com' } });
        fireEvent.click(button);

        await waitFor(() => {
            expect(screen.getByText(/An error occurred while sending the request./i)).toBeDefined();
        });
    });

    test('zeigt Fehlermeldung bei nicht erfolgreicher Antwort', async () => {
        (fetch as unknown as vi.Mock).mockResolvedValueOnce({
            ok: false,
            json: async () => ({ detail: 'Request rejected' }),
        });

        render(<ForgotPassword />);
        const input = screen.getByLabelText(/E-Mail/i);
        const button = screen.getByRole('button', { name: /Reset Password/i });

        fireEvent.change(input, { target: { value: 'reject@example.com' } });
        fireEvent.click(button);

        await waitFor(() => {
            expect(screen.getByText(/Request rejected/i)).toBeDefined();
        });
    });
});
