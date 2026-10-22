import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import ForgotPassword from '../pages/ForgotPassword';
import { vi } from 'vitest';
import { API_CONFIG, getApiUrl } from '@/lib/api-config';

const fetchMock = vi.fn<typeof fetch>();
const renderForgotPassword = () => render(<ForgotPassword />, { wrapper: MemoryRouter });

const requestReset = (email: string) => {
    renderForgotPassword();
    fireEvent.change(screen.getByLabelText(/Email/i), { target: { value: email } });
    fireEvent.click(screen.getByRole('button', { name: /Reset Password/i }));
};

describe('ForgotPassword', () => {
    beforeEach(() => {
        vi.resetAllMocks();
        vi.stubGlobal('fetch', fetchMock);
        vi.spyOn(console, 'error').mockImplementation(() => undefined);
    });

    test('sends the address and shows the confirmation', async () => {
        fetchMock.mockResolvedValueOnce(new Response(
            JSON.stringify({ message: 'Reset link sent' }),
            { status: 200, headers: { 'Content-Type': 'application/json' } }
        ));

        requestReset('test@example.com');

        await waitFor(() => {
            expect(screen.getByText(/Reset link sent/i)).toBeDefined();
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

    test.each([
        ['an unreachable server', () => Promise.reject(new Error('Failed')), /An error occurred while sending the request./i],
        [
            'a rejected request',
            () => Promise.resolve(new Response(
                JSON.stringify({ detail: 'Request rejected' }),
                { status: 400, headers: { 'Content-Type': 'application/json' } }
            )),
            /Request rejected/i,
        ],
    ])('reports %s', async (_, respond, message) => {
        fetchMock.mockImplementationOnce(respond);

        requestReset('test@example.com');

        await waitFor(() => {
            expect(screen.getByText(message)).toBeDefined();
        });
    });
});
