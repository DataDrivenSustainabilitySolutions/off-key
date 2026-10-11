import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Settings from "../pages/Settings";
import type { StorageStatus } from "../types/collection";

const api = vi.hoisted(() => ({ get: vi.fn() }));
const getStorage = vi.fn();
const auth = vi.hoisted(() => ({ isAdmin: true, member: { email: "admin@example.com" } }));
vi.mock("../lib/api-client", () => ({ apiUtils: api }));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => auth }));
vi.mock("../components/NavigationBar", () => ({ NavigationBar: () => null }));
const status: StorageStatus = {
  database_size_bytes: 1500000000,
  retention_policies: [
    { table: "telemetry", retention_days: 30, scheduled: true },
    { table: "monitoring_evidence", retention_days: 7, scheduled: true },
  ],
  checked_at: "2026-09-27T12:00:00Z",
};
beforeEach(() => {
  vi.clearAllMocks();
  getStorage.mockResolvedValue(status);
  api.get.mockImplementation((url) => url === "/v1/sources/storage"
    ? getStorage()
    : Promise.resolve({ revision: 0, collection: {}, ingress: {} }));
});

describe("storage and retention", () => {
  it.each([true, false])("loads storage settings (administrator: %s)", async (isAdmin) => {
    auth.isAdmin = isAdmin;
    render(
      <MemoryRouter initialEntries={["/account/settings"]}>
        <Settings />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { name: "Settings", level: 1 })).toBeTruthy();
    expect(await screen.findByText("1.5 GB")).toBeTruthy();
    expect(screen.getByText("30 days")).toBeTruthy();
    expect(screen.getByText("7 days")).toBeTruthy();
    expect(api.get).toHaveBeenCalledWith("/v1/sources/storage");
    expect(screen.getByRole("heading", { name: "Collection diagnostics" })).toBeTruthy();
    expect(screen.getByText("Not configured")).toBeTruthy();
    expect(api.get).toHaveBeenCalledWith("/v1/sources/status");
    expect(api.get).not.toHaveBeenCalledWith("/v1/sources");
  });

  it("distinguishes paused and missing policies without substituting defaults", async () => {
    getStorage.mockResolvedValue({
      ...status,
      retention_policies: [
        { table: "telemetry", retention_days: 30, scheduled: false },
        { table: "monitoring_evidence", retention_days: null, scheduled: false },
      ],
    });
    render(<MemoryRouter><Settings /></MemoryRouter>);
    expect(await screen.findByText("Cleanup paused")).toBeTruthy();
    const evidence = screen.getByText("Monitoring evidence retention").parentElement!;
    expect(within(evidence).getByText("Not configured")).toBeTruthy();
    expect(screen.queryByText("14 days")).toBeNull();
  });

  it("reports failures and refreshes measurements on request", async () => {
    getStorage.mockRejectedValueOnce(new Error("Database unavailable"));
    render(<MemoryRouter><Settings /></MemoryRouter>);
    expect((await screen.findByRole("alert")).textContent).toContain("Storage information unavailable");
    expect(screen.queryByText("0 MB")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Refresh storage" }));
    expect(await screen.findByText("1.5 GB")).toBeTruthy();
    getStorage.mockResolvedValue({ ...status, database_size_bytes: 500000000 });
    fireEvent.click(screen.getByRole("button", { name: "Refresh storage" }));
    expect(await screen.findByText("500 MB")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
