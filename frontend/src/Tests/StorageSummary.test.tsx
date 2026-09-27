import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StorageSummary } from "../pages/sources/StorageSummary";
import type { StorageStatus } from "../types/collection";

const api = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("../lib/api-client", () => ({ apiUtils: api }));
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
  it("shows measured database size and each applied retention policy", async () => {
    render(<StorageSummary />);
    expect(await screen.findByText("1.5 GB")).toBeTruthy();
    expect(screen.getByText("30 days")).toBeTruthy();
    expect(screen.getByText("7 days")).toBeTruthy();
    expect(api.get).toHaveBeenCalledWith("/v1/sources/storage");
  });

  it("distinguishes paused and missing policies without substituting defaults", async () => {
    api.get.mockResolvedValue({
      ...status,
      retention_policies: [
        { table: "telemetry", retention_days: 30, scheduled: false },
        { table: "monitoring_evidence", retention_days: null, scheduled: false },
      ],
    });
    render(<StorageSummary />);
    expect(await screen.findByText("Automatic cleanup paused.")).toBeTruthy();
    expect(screen.getByText("Not configured")).toBeTruthy();
    expect(screen.queryByText("14 days")).toBeNull();
  });

  it("reports failures and refreshes measurements on request", async () => {
    api.get.mockRejectedValueOnce(new Error("Database unavailable"));
    render(<StorageSummary />);
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
