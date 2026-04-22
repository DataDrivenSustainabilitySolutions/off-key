import React from "react";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, test, vi } from "vitest";

import Favourites from "../pages/Favourites";

const mockGetFavorites = vi.fn();
const mockGetAllChargers = vi.fn();
const mockGetCombinedChargerData = vi.fn();
const mockToggleFavorite = vi.fn();

vi.mock("../dataFetch/UseFetch", () => ({
  useFetch: () => ({
    getFavorites: mockGetFavorites,
    getAllChargers: mockGetAllChargers,
    getCombinedChargerData: mockGetCombinedChargerData,
    toggleFavorite: mockToggleFavorite,
  }),
}));

vi.mock("../components/NavigationBar", () => ({
  NavigationBar: () => <div data-testid="navigation-bar" />,
}));

describe("Favourites", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetFavorites.mockResolvedValue(["CH-001"]);
    mockGetAllChargers.mockResolvedValue([
      {
        charger_id: "CH-001",
        charger_name: "Alpha Charger",
        last_seen: "2026-04-14T10:00:00Z",
        online: true,
        state: "ready",
        created: "2026-04-14T09:00:00Z",
      },
      {
        charger_id: "CH-002",
        charger_name: "Beta Charger",
        last_seen: "2026-04-14T10:00:00Z",
        online: false,
        state: "offline",
        created: "2026-04-14T09:00:00Z",
      },
    ]);
    mockGetCombinedChargerData.mockResolvedValue([
      {
        charger_id: "CH-001",
        charger_name: "Alpha Charger",
        last_seen: "2026-04-14T10:00:00Z",
        online: true,
        state: "ready",
      },
      {
        charger_id: "CH-002",
        charger_name: "Beta Charger",
        last_seen: "2026-04-14T10:00:00Z",
        online: false,
        state: "offline",
      },
    ]);
  });

  test("renders search input, filters, and favorite charger data", async () => {
    render(
      <MemoryRouter>
        <Favourites />
      </MemoryRouter>
    );

    expect(screen.getByPlaceholderText(/search for charger id/i)).toBeTruthy();
    expect(await screen.findByText(/charger id/i)).toBeTruthy();
    expect(screen.getByText("CH-001")).toBeTruthy();
    expect(screen.queryByText("CH-002")).toBeNull();
  });
});
