import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Account from "../pages/Account";
import Settings from "../pages/Settings";
import type { StorageStatus } from "../types/collection";

const api = vi.hoisted(() => ({ get: vi.fn() }));
const auth = vi.hoisted(() => ({ isAdmin: true, member: { email: "admin@example.com" } }));
vi.mock("../lib/api-client", () => ({ apiUtils: api }));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => auth }));
vi.mock("../components/NavigationBar", () => ({ NavigationBar: () => null }));
vi.mock("../lib/member-api", () => ({ getMembers: vi.fn().mockResolvedValue([]) }));
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
  api.get.mockResolvedValue(status);
});

describe("storage and retention", () => {
  it.each([true, false])("opens storage settings through Account (administrator: %s)", async (isAdmin) => {
    auth.isAdmin = isAdmin;
    render(
      <MemoryRouter initialEntries={["/account"]}>
        <Routes>
          <Route path="/account" element={<Account />} />
          <Route path="/account/settings" element={<Settings />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(api.get).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("link", { name: "Settings" }));
    expect(screen.getByRole("heading", { name: "Settings", level: 1 })).toBeTruthy();
    expect(await screen.findByText("1.5 GB")).toBeTruthy();
    expect(screen.getByText("30 days")).toBeTruthy();
    expect(screen.getByText("7 days")).toBeTruthy();
    expect(api.get).toHaveBeenCalledWith("/v1/sources/storage");
    fireEvent.click(screen.getByRole("link", { name: "Back to account" }));
    expect(screen.getByRole("heading", { name: "Account", level: 1 })).toBeTruthy();
  });

  it("distinguishes paused and missing policies without substituting defaults", async () => {
    api.get.mockResolvedValue({
      ...status,
      retention_policies: [
        { table: "telemetry", retention_days: 30, scheduled: false },
        { table: "monitoring_evidence", retention_days: null, scheduled: false },
      ],
    });
    render(<MemoryRouter><Settings /></MemoryRouter>);
    expect(await screen.findByText("Cleanup paused")).toBeTruthy();
    expect(screen.getByText("Not configured")).toBeTruthy();
    expect(screen.queryByText("14 days")).toBeNull();
  });

  it("reports failures and refreshes measurements on request", async () => {
    api.get.mockRejectedValueOnce(new Error("Database unavailable"));
    render(<MemoryRouter><Settings /></MemoryRouter>);
    expect((await screen.findByRole("alert")).textContent).toContain("Storage information unavailable");
    expect(screen.queryByText("0 MB")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Refresh storage" }));
    expect(await screen.findByText("1.5 GB")).toBeTruthy();
    api.get.mockResolvedValue({ ...status, database_size_bytes: 500000000 });
    fireEvent.click(screen.getByRole("button", { name: "Refresh storage" }));
    expect(await screen.findByText("500 MB")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
