import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AuthProvider } from "@/auth/AuthContext";
import Landingpage from "./Landingpage";

function setup() {
    render(
        <AuthProvider>
            <MemoryRouter>
                <Landingpage />
            </MemoryRouter>
        </AuthProvider>
    );
}

describe("Landingpage UI", () => {
    test("zeigt 'Lade Daten...' während initialem Ladezustand", () => {
        setup();
        expect(screen.getByText(/lade daten/i)).to.exist;
    });

    test("Suchfeld aktualisiert Suchbegriff", () => {
        setup();
        const input = screen.getByPlaceholderText(/nach charger id/i) as HTMLInputElement;
        expect(input.value).to.equal("");
        fireEvent.change(input, { target: { value: "1234" } });
        expect(input.value).to.equal("1234");
    });

    test("Umschalten zwischen Table und Cards", () => {
        setup();
        const toggle = screen.getByRole("switch");
        expect(toggle.getAttribute("aria-checked")).to.equal("false");
        fireEvent.click(toggle);
        expect(toggle.getAttribute("aria-checked")).to.equal("true");
    });

    test("Filterstatus umschalten (z. B. auf offline)", () => {
        setup();
        const offlineRadio = screen.getByLabelText(/offline/i) as HTMLInputElement;
        expect(offlineRadio.checked).to.be.false;
        fireEvent.click(offlineRadio);
        expect(offlineRadio.checked).to.be.true;
    });
});
