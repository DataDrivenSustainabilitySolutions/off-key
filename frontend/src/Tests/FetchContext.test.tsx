import React from 'react'; // ✅ Required for React.useContext
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { FetchProvider, FetchContext } from '../dataFetch/FetchContext';
import axios from 'axios';

vi.mock('axios');
const mockAxios = axios as unknown as {
    get: ReturnType<typeof vi.fn>;
    post: ReturnType<typeof vi.fn>;
    delete: ReturnType<typeof vi.fn>;
};

const wrapper = ({ children }: { children: React.ReactNode }) => (
    <FetchProvider>{children}</FetchProvider>
);

describe('FetchContext logic', () => {
    beforeEach(() => {
        vi.resetAllMocks();
    });

    it('fetches telemetry types', async () => {
        mockAxios.get = vi.fn().mockResolvedValueOnce({ data: ['controllerCpuUsage'] });

        const { result } = renderHook(() => React.useContext(FetchContext), { wrapper });
        const types = await result.current?.getTelemetryTypes?.('abc-123');

        expect(types).toEqual(['controllerCpuUsage']);
        expect(mockAxios.get).toHaveBeenCalledWith(
            'http://127.0.0.1:8000/v1/telemetry/abc-123/type'
        );
    });

    it('fetches favorites', async () => {
        mockAxios.get = vi.fn().mockResolvedValueOnce({ data: ['abc123'] });

        const { result } = renderHook(() => React.useContext(FetchContext), { wrapper });
        const favorites = await result.current?.getFavorites?.(1);

        expect(favorites).toEqual(['abc123']);
        expect(mockAxios.get).toHaveBeenCalledWith(
            'http://127.0.0.1:8000/v1/favorites?user_id=1'
        );
    });

    it('adds a favorite', async () => {
        mockAxios.post = vi.fn().mockResolvedValueOnce({});

        const { result } = renderHook(() => React.useContext(FetchContext), { wrapper });
        await act(() => result.current?.toggleFavorite?.('charger-1', 1, false));

        expect(mockAxios.post).toHaveBeenCalledWith(
            'http://127.0.0.1:8000/v1/favorites',
            { charger_id: 'charger-1', user_id: 1 }
        );
    });

    it('removes a favorite', async () => {
        mockAxios.delete = vi.fn().mockResolvedValueOnce({});

        const { result } = renderHook(() => React.useContext(FetchContext), { wrapper });
        await act(() => result.current?.toggleFavorite?.('charger-1', 1, true));

        expect(mockAxios.delete).toHaveBeenCalledWith(
            'http://127.0.0.1:8000/v1/favorites',
            { data: { charger_id: 'charger-1', user_id: 1 } }
        );
    });

    it('loads CPU usage data correctly', async () => {
        mockAxios.get = vi
            .fn()
            .mockResolvedValueOnce({ data: ['controllerCpuUsage'] }) // types
            .mockResolvedValueOnce({ data: [{ timestamp: 'now', value: 70 }] }); // telemetry

        const { result } = renderHook(() => React.useContext(FetchContext), { wrapper });
        await act(() => result.current?.loadCpuUsage?.('chargerX'));

        const data = result.current?.cpuUsageMap['chargerX'];
        expect(data?.[0].value).toBe(70);
    });

    it('sets searchError when telemetry types not found', async () => {
        mockAxios.get = vi.fn().mockResolvedValueOnce({ data: [] });

        const { result } = renderHook(() => React.useContext(FetchContext), { wrapper });
        await act(() => result.current?.loadCpuUsage?.('chargerY'));

        expect(result.current?.searchError).toBe(true);
    });
});
