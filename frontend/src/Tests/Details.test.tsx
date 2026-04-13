import { describe, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "../auth/AuthContext";
import { FetchProvider } from "../dataFetch/FetchContext";
import Details from "../pages/Details";

// ResizeObserver mock (für recharts)
global.ResizeObserver = class {
    observe() { }
    unobserve() { }
    disconnect() { }
};

// Axios mock
vi.mock("axios", () => ({
    default: {
        get: vi.fn((url) => {
            if (url.includes("metrics")) {
                return Promise.resolve({
                    data: [
                        {
                            timestamp: new Date().toISOString(),
                            value: Math.random() * 100,
                        },
                    ],
                });
            }

            if (url.includes("chargers/123")) {
                return Promise.resolve({
                    data: {
                        charger_id: "123",
                        charger_name: "Test Charger",
                    },
                });
            }

            return Promise.resolve({ data: [] });
        }),
    },
}));

// useRedZones mock
vi.mock("../lib/useRedZones", () => ({
    useRedZones: () => [],
}));

function renderWithProviders() {
    return render(
        <AuthProvider>
            <FetchProvider>
                <MemoryRouter initialEntries={["/details/123"]}>
                    <Routes>
                        <Route path="/details/:charger_id" element={<Details />} />
                    </Routes>
                </MemoryRouter>
            </FetchProvider>
        </AuthProvider>
    );
}

describe("<Details />", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("zeigt CPU-Karten", async () => {
        renderWithProviders();
        const cpu = await screen.findByText(/CPU Usage/i);
        const thermal = screen.queryByText(/CPU Thermal/i);

        expect(cpu).not.toBeNull();
        expect(thermal).not.toBeNull();
    });

    it("zeigt Zeitfilter und Datumseingaben", async () => {
        renderWithProviders();
        await screen.findByText(/CPU Usage/i);

        const fromInputs = screen.queryAllByPlaceholderText(/From/i);
        const toInputs = screen.queryAllByPlaceholderText(/To/i);
        expect(fromInputs.length).toBeGreaterThan(0);
        expect(toInputs.length).toBeGreaterThan(0);
    });

    it("zeigt Link zu Monitoring", async () => {
        renderWithProviders();

        // warte auf Text der erst gerendert wird, wenn charger_id geladen ist
        await screen.findByText(/CPU Usage/i);

        const link = screen.getByRole("link", { name: /Monitoring/i });
        expect(link).not.toBeNull();
    });


    it("klappt CPU-Karten ein/aus", async () => {
        renderWithProviders();
        await screen.findByText(/CPU Usage/i);

        const buttons = screen.getAllByRole("button");
        expect(buttons.length).toBeGreaterThan(0);

        fireEvent.click(buttons[0]);
        fireEvent.click(buttons[1]);

        const stillThere = screen.queryByText(/CPU Usage/i);
        expect(stillThere).not.toBeNull();
    });
});
