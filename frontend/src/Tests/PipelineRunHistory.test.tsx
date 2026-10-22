import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { pipelinesApi } from "@/features/pipelines/api";
import { PipelineRunHistory } from "@/features/pipelines/PipelineRunHistory";
import type { PipelineRunSummary } from "@/types/pipelines.generated";

vi.mock("@/features/pipelines/api", () => ({ pipelinesApi: { history: vi.fn() } }));

const run = (id: string, serviceId: string): PipelineRunSummary => ({
  id,
  service_id: serviceId,
  revision_id: null,
  predecessor_run_id: null,
  status: "stopped",
  created_at: "2026-10-20T12:00:00Z",
  ended_at: null,
});

function renderHistory(items: PipelineRunSummary[], next: string | null) {
  render(
    <MemoryRouter>
      <PipelineRunHistory initial={{ items, next_service_id: next }} />
    </MemoryRouter>,
  );
}

const loadOlder = () =>
  fireEvent.click(screen.getByRole("button", { name: "Load older monitoring history" }));
const listed = () => screen.getAllByRole("link").map((link) => link.textContent);

describe("linked monitoring history", () => {
  beforeEach(() => vi.resetAllMocks());

  it("pages older runs without repeating any and links each to its service", async () => {
    vi.mocked(pipelinesApi.history)
      .mockResolvedValueOnce({ items: [run("run-3", "svc 3"), run("run-2", "svc-2")], next_service_id: "svc-1" })
      .mockResolvedValueOnce({ items: [run("run-1", "svc-1")], next_service_id: null });
    renderHistory([run("run-3", "svc 3")], "svc-2");

    expect(screen.getByText("Linked monitoring history (1+)")).toBeTruthy();
    expect(screen.getByRole("link", { name: "run-3" }).getAttribute("href")).toBe(
      "/?service=svc%203&tab=pipeline",
    );
    loadOlder();
    expect(await screen.findByText("Linked monitoring history (2+)")).toBeTruthy();
    loadOlder();

    expect(await screen.findByText("Linked monitoring history (3)")).toBeTruthy();
    expect(listed()).toEqual(["run-3", "run-2", "run-1"]);
    expect(vi.mocked(pipelinesApi.history).mock.calls).toEqual([["svc-2"], ["svc-1"]]);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("stops paging when the next page points back into the listed history", async () => {
    vi.mocked(pipelinesApi.history).mockResolvedValueOnce({
      items: [run("run-1", "svc-1")],
      next_service_id: "svc-2",
    });
    renderHistory([run("run-2", "svc-2")], "svc-1");

    loadOlder();

    expect(await screen.findByText("Linked monitoring history (2)")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("keeps the listed runs and offers another try when a page fails", async () => {
    vi.mocked(pipelinesApi.history).mockRejectedValueOnce(new Error("History unavailable"));
    renderHistory([run("run-2", "svc-2")], "svc-1");

    loadOlder();

    expect((await screen.findByRole("alert")).textContent).toBe("History unavailable");
    expect(listed()).toEqual(["run-2"]);
    expect(
      screen.getByRole<HTMLButtonElement>("button", { name: "Load older monitoring history" }).disabled,
    ).toBe(false);
  });
});
