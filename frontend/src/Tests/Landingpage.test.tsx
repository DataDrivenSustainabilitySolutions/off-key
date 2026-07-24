import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, test, vi } from "vitest";

import Landingpage from "@/pages/Landingpage";

const { mockGetAllChargers, mockGetFavorites, mockToggleFavorite } = vi.hoisted(
  () => ({
    mockGetAllChargers: vi.fn(),
    mockGetFavorites: vi.fn(),
    mockToggleFavorite: vi.fn(),
  }),
);

vi.mock("@/lib/charger-api", () => ({
  getAllChargers: mockGetAllChargers,
  getFavorites: mockGetFavorites,
  toggleFavorite: mockToggleFavorite,
}));

vi.mock("@/auth/AuthContext", () => ({
  useAuth: () => ({ userId: 1 }),
}));

vi.mock("@/components/NavigationBar", () => ({
  NavigationBar: () => <div data-testid="navigation-bar" />,
}));

function renderLandingpage() {
  render(
    <MemoryRouter>
      <Landingpage />
    </MemoryRouter>
  );
}

describe("Landingpage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetAllChargers.mockImplementation(
      () => new Promise(() => undefined)
    );
    mockGetFavorites.mockImplementation(() => new Promise(() => undefined));
  });

  test("shows a loading indicator before data resolves", () => {
    renderLandingpage();

    expect(screen.getByText(/loading data/i)).toBeTruthy();
  });

  test("shows the search field and allows input", async () => {
    renderLandingpage();

    const input = screen.getByPlaceholderText(/search by charger id/i);
    fireEvent.change(input, { target: { value: "ABC123" } });

    expect((input as HTMLInputElement).value).toBe("ABC123");
    await waitFor(() => {
      expect(mockGetAllChargers).toHaveBeenCalled();
    });
  });

  test("shows status filter radio buttons", () => {
    renderLandingpage();

    expect(screen.getByLabelText(/offline/i)).toBeTruthy();
    expect(screen.getByLabelText(/online/i)).toBeTruthy();
    expect(screen.getByLabelText(/all/i)).toBeTruthy();
  });

  test("shows the cards-view toggle", () => {
    renderLandingpage();

    expect(screen.getByRole("switch")).toBeTruthy();
  });
});
