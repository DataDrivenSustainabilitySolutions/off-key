import React from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import axios from 'axios';
import { vi } from 'vitest';
import { FetchProvider } from '../dataFetch/FetchContext';

import Favourites from '../pages/Favourites';
import { AuthProvider } from '../auth/AuthContext';  // Pfad anpassen

vi.mock('axios');

describe('Favourites', () => {
    beforeEach(() => {
        (axios.get as vi.Mock).mockReset();
    });

    test('renders search input, filters and table headers', async () => {
        (axios.get as vi.Mock).mockResolvedValue({
            data: [
                { id: '1', status: 'online', chargerId: 'CH-001' },
            ],
        });

        render(
            <AuthProvider>
                <FetchProvider>
                    <MemoryRouter>
                        <Favourites />
                    </MemoryRouter>
                </FetchProvider>
            </AuthProvider>
        );

        screen.getByPlaceholderText(/Search for charger ID.../i);
        await screen.findByText(/Charger ID/i);
    });
});
