import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AuthProvider } from "@/auth/AuthContext";
import { FetchProvider } from "@/dataFetch/FetchContext";
import Landingpage from "@/pages/Landingpage";

function renderLandingpage() {
    render(
        <AuthProvider>
            <FetchProvider>
                <MemoryRouter>
                    <Landingpage />
                </MemoryRouter>
            </FetchProvider>
        </AuthProvider>
    );
}

describe("Landingpage UI ohne Mocks und ohne toBeInTheDocument", () => {
    test("zeigt Ladeanzeige an", () => {
        renderLandingpage();
        const loading = screen.getByText(/loading data/i);
        expect(loading).not.toBeNull();
    });

    test("zeigt Suchfeld und erlaubt Eingabe", () => {
        renderLandingpage();
        const input = screen.getByPlaceholderText(/search by charger id/i);
        expect(input).not.toBeNull();

        fireEvent.change(input, { target: { value: "ABC123" } });
        expect((input as HTMLInputElement).value).toBe("ABC123");
    });

    test("zeigt Statusfilter Radio-Buttons", () => {
        renderLandingpage();

        const offline = screen.getByLabelText(/offline/i);
        const online = screen.getByLabelText(/online/i);
        const all = screen.getByLabelText(/all/i);

        expect(offline).not.toBeNull();
        expect(online).not.toBeNull();
        expect(all).not.toBeNull();
    });

    test("zeigt Toggle für Kartenansicht", () => {
        renderLandingpage();
        const toggle = screen.getByRole("switch");
        expect(toggle).not.toBeNull();
    });
});
