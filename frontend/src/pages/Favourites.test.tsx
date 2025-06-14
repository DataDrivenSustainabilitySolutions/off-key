import React from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import axios from 'axios';
import { vi } from 'vitest';

import Favourites from './Favourites';
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
                <MemoryRouter>
                    <Favourites />
                </MemoryRouter>
            </AuthProvider>
        );

        screen.getByPlaceholderText(/Nach Charger ID suchen/i);
        screen.getByText(/Ladesäulen Status/i);
        await screen.findByText(/Charger ID/i);
    });
});
