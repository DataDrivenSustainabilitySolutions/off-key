import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HistoryValues } from "@/features/charts/HistoryValues";

const at = (minutes: number) => new Date(Date.UTC(2026, 10, 27, 14, minutes, 59)).toISOString();

describe("values behind a chart", () => {
  it("lists readings newest first with readable times and English numbers", () => {
    render(<HistoryValues unit="kWh" history={{ representation: "raw", interval_ms: 0, sample_count: 1036, extent: null, column_ms: 2000,
      points: [{ timestamp: at(28), value: 39.4 }, { timestamp: at(29), value: 1234.5 }] }} />);
    const table = screen.getByRole("region", { name: "Values" });
    expect(table.textContent).toContain("2 of 1,036 readings");
    const rows = within(table).getAllByRole("row").slice(1);
    const first = within(rows[0]!).getByText(/27/, { selector: "time" });
    expect(first.getAttribute("datetime")).toBe(at(29));
    expect(first.textContent).toMatch(/^Nov 27, \d\d:29:59$/);
    expect(first.textContent).not.toContain("T");
    expect(within(table).getByText("Measured at", { exact: true })).toBeTruthy();
  });

  it("keeps sub-second readings apart and the original timestamp on hover", () => {
    const early = "2026-11-27T14:29:59.001Z";
    const late = "2026-11-27T14:29:59.999Z";
    render(<HistoryValues history={{ representation: "raw", interval_ms: 0, sample_count: 2, extent: null,
      points: [{ timestamp: early, value: 1 }, { timestamp: late, value: 2 }] }} />);
    const times = screen.getAllByText(/:29:59/, { selector: "time" });
    expect(times.map(time => time.textContent)).toEqual([expect.stringMatching(/:29:59\.999$/), expect.stringMatching(/:29:59\.001$/)]);
    expect(times.map(time => time.getAttribute("title"))).toEqual([late, early]);
  });

  it("says what averaged rows summarise", () => {
    render(<HistoryValues history={{ representation: "mean", interval_ms: 30_000, sample_count: 3600, extent: null,
      points: [{ timestamp: at(29), start: at(29), value: 12.34567, minimum: 10, maximum: 15, count: 1200 }] }} />);
    const table = screen.getByRole("region", { name: "Values" });
    expect(table.textContent).toContain("of 3,600 readings");
    expect(within(table).getByText("1,200")).toBeTruthy();
  });
});
