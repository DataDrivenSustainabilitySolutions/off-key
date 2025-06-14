import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import ForgotPassword from './ForgotPassword';
import { vi } from 'vitest';

// Mock fetch global
global.fetch = vi.fn();

describe('ForgotPassword', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    test('render form elements', () => {
        render(<ForgotPassword />);
        expect(screen.queryByLabelText(/E-Mail/i)).not.toBeNull();
        expect(screen.queryByRole('button', { name: /Password zurücksetzen/i })).not.toBeNull();
    });

    test('allows typing in email input', () => {
        render(<ForgotPassword />);
        const emailInput = screen.getByLabelText(/E-Mail/i);
        fireEvent.change(emailInput, { target: { value: 'test@example.com' } });
        expect(emailInput.value).toBe('test@example.com');

    });

    test('shows success message after form submit', async () => {
        (fetch as jest.Mock).mockResolvedValueOnce({
            json: async () => ({ message: 'Reset link gesendet!' }),
        });

        render(<ForgotPassword />);
        const emailInput = screen.getByLabelText(/E-Mail/i);
        const button = screen.getByRole('button', { name: /Password zurücksetzen/i });

        fireEvent.change(emailInput, { target: { value: 'test@example.com' } });
        fireEvent.click(button);

        await waitFor(() => {
            expect(screen.queryByText('Reset link gesendet!')).not.toBeNull();
        });

        expect(fetch).toHaveBeenCalledWith(
            'http://localhost:8000/v1/auth/forgot-password',
            expect.objectContaining({
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: 'test@example.com' }),
            })
        );
    });

    test('shows error message on fetch failure', async () => {
        (fetch as jest.Mock).mockRejectedValueOnce(new Error('Failed'));

        render(<ForgotPassword />);
        const emailInput = screen.getByLabelText(/E-Mail/i);
        const button = screen.getByRole('button', { name: /Password zurücksetzen/i });

        fireEvent.change(emailInput, { target: { value: 'fail@example.com' } });
        fireEvent.click(button);

        await waitFor(() => {
            expect(screen.queryByText('Fehler beim Senden der Anfrage.')).not.toBeNull();
        });
    });
});
