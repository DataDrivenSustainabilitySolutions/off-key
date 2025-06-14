// src/pages/Details.test.tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "../auth/AuthContext";
import Details from "./Details";

// 🔧 ResizeObserver mock (für recharts)
global.ResizeObserver = class {
    observe() { }
    unobserve() { }
    disconnect() { }
};

// Axios-Mock
vi.mock("axios", () => ({
    default: {
        get: vi.fn(() => Promise.resolve({ data: [] })),
    },
}));

// RedZones-Hook mocken (optional)
vi.mock("../lib/useRedZones", () => ({
    useRedZones: () => [],
}));

// Hilfsfunktion zum Einbetten in Router & Provider
function renderWithProviders() {
    return render(
        <AuthProvider>
            <MemoryRouter initialEntries={["/details/123"]}>
                <Routes>
                    <Route path="/details/:charger_id" element={<Details />} />
                </Routes>
            </MemoryRouter>
        </AuthProvider>
    );
}

describe("<Details />", () => {
    beforeEach(() => {
        vi.resetAllMocks();
    });

    it("renders Charger ID title and CPU cards", async () => {
        renderWithProviders();

        const title = await screen.findByText(/Charger 123/);
        expect(title).not.toBeNull();

        const cpuUsage = screen.queryByText(/CPU Usage/);
        const cpuThermal = screen.queryByText(/CPU Thermal/);
        expect(cpuUsage).not.toBeNull();
        expect(cpuThermal).not.toBeNull();
    });

    it("shows date inputs and time range buttons", async () => {
        renderWithProviders();

        const vonInputs = await screen.findAllByPlaceholderText("Von");
        const bisInputs = screen.getAllByPlaceholderText("Bis");
        expect(vonInputs).toHaveLength(2);
        expect(bisInputs).toHaveLength(2);

        expect(screen.queryByText("Letzte Minute")).not.toBeNull();
        const timeButtons = screen.getAllByText("Letzte 10 Minutes");
        expect(timeButtons.length).toBeGreaterThan(0);

    });

    it("clicks collapse buttons for CPU cards", async () => {
        renderWithProviders();

        const collapseButtons = screen.getAllByRole("button", { hidden: true });
        expect(collapseButtons.length).toBeGreaterThanOrEqual(2);

        fireEvent.click(collapseButtons[0]);
        fireEvent.click(collapseButtons[1]);

        const cpuUsage = screen.queryByText("CPU Usage");
        const cpuThermal = screen.queryByText("CPU Thermal");
        expect(cpuUsage).not.toBeNull();
        expect(cpuThermal).not.toBeNull();
    });
});
