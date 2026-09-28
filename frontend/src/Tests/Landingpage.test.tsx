import {
  act,
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, test, vi } from "vitest";
import toast from "react-hot-toast";

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
vi.mock("react-hot-toast", () => ({
  default: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("@/lib/logger", () => ({ clientLogger: { error: vi.fn() } }));

function renderLandingpage(path = "/") {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Landingpage />
    </MemoryRouter>,
  );
}

const chargers = [
  { charger_id: "CH-001", charger_name: "Alpha", online: true },
  { charger_id: "CH-002", charger_name: "Beta", online: false },
  { charger_id: "CH-003", charger_name: "Gamma", online: true },
].map((charger) => ({
  ...charger,
  last_seen: "2026-09-28T12:00:00Z",
  state: charger.online ? "ready" : "offline",
  created: "2026-09-28T09:00:00Z",
}));

function loadChargers() {
  mockGetAllChargers.mockResolvedValue(chargers);
  mockGetFavorites.mockResolvedValue(["CH-001", "CH-002", "retired-charger"]);
  mockToggleFavorite.mockResolvedValue(undefined);
}

describe("Landingpage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetAllChargers.mockImplementation(() => new Promise(() => undefined));
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
    expect(screen.getByRole("radio", { name: /favorites/i })).toBeTruthy();
  });

  test("shows the cards-view toggle", () => {
    renderLandingpage();

    expect(screen.getByRole("switch")).toBeTruthy();
  });

  test("filters favorites across charger states and combines them with search and card view", async () => {
    loadChargers();
    renderLandingpage("/?state=favorites");
    expect(await screen.findByText("CH-001")).toBeTruthy();
    expect(screen.getByText("CH-002")).toBeTruthy();
    expect(screen.queryByText("CH-003")).toBeNull();
    expect(
      (screen.getByRole("radio", { name: "Favorites (2)" }) as HTMLInputElement)
        .checked,
    ).toBe(true);
    expect(mockGetFavorites).toHaveBeenCalledWith();

    const search = screen.getByRole("textbox");
    fireEvent.change(search, { target: { value: "beta" } });
    expect(screen.queryByText("CH-001")).toBeNull();
    expect(screen.getByText("CH-002")).toBeTruthy();
    fireEvent.click(screen.getByRole("switch"));
    expect(
      screen.getByRole("link", { name: "More details" }).getAttribute("href"),
    ).toBe("/details/CH-002");
    fireEvent.change(search, { target: { value: "CH-003" } });
    expect(screen.getByText("No data found.")).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: "All (3)" }));
    expect(screen.getByText("CH-003")).toBeTruthy();
  });

  test("keeps online and offline filters independent of favorites", async () => {
    loadChargers();
    renderLandingpage();
    await screen.findByText("CH-001");
    fireEvent.click(screen.getByRole("radio", { name: "Offline (1)" }));
    expect(screen.getByText("CH-002")).toBeTruthy();
    expect(screen.queryByText("CH-001")).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: "Online (2)" }));
    expect(screen.getByText("CH-001")).toBeTruthy();
    expect(screen.getByText("CH-003")).toBeTruthy();
    expect(screen.queryByText("CH-002")).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: "Favorites (2)" }));
    expect(screen.getByText("CH-002")).toBeTruthy();
    expect(screen.queryByText("CH-003")).toBeNull();
  });

  test("updates the favorites list and count immediately when a star is removed", async () => {
    loadChargers();
    renderLandingpage("/?state=favorites");
    const charger = await screen.findByText("CH-001");
    fireEvent.click(
      within(charger.closest("tr")!).getByRole("button", {
        name: "Toggle favorite",
      }),
    );
    expect(screen.queryByText("CH-001")).toBeNull();
    expect(screen.getByRole("radio", { name: "Favorites (1)" })).toBeTruthy();
    await waitFor(() =>
      expect(mockToggleFavorite).toHaveBeenCalledWith("CH-001", true),
    );
    fireEvent.click(screen.getByRole("radio", { name: "All (3)" }));
    expect(
      within(screen.getByText("CH-001").closest("tr")!)
        .getByRole("button", { name: "Toggle favorite" })
        .getAttribute("aria-pressed"),
    ).toBe("false");
  });

  test("restores the favorite and count if saving its removal fails", async () => {
    loadChargers();
    let fail: (reason: Error) => void = () => {};
    mockToggleFavorite.mockImplementation(
      () =>
        new Promise((_, reject) => {
          fail = reject;
        }),
    );
    renderLandingpage("/?state=favorites");
    const charger = await screen.findByText("CH-001");
    fireEvent.click(
      within(charger.closest("tr")!).getByRole("button", {
        name: "Toggle favorite",
      }),
    );
    expect(screen.queryByText("CH-001")).toBeNull();
    await act(async () => fail(new Error("Unavailable")));
    expect(screen.getByText("CH-001")).toBeTruthy();
    expect(screen.getByRole("radio", { name: "Favorites (2)" })).toBeTruthy();
    expect(toast.error).toHaveBeenCalledWith(
      "Failed to update favorite status",
    );
  });
});
