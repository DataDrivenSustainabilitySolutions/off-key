import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { alarmSpans, buildStripPills, lensOptics, locateOnStrip, STRIP, type StripRow } from "@/features/charts/anomaly-strip";
import { monitorColors } from "@/features/charts/monitor-colors";
import { MonitorViews, RAW_VIEW } from "@/features/charts/MonitorViews";

const row = (id: string, spans: Array<[number, number]>): StripRow => ({ id, name: id, color: id, spans });
const names = (rows: StripRow[]) => rows.map(item => item.id);

describe("anomaly strip", () => {
  it("reads consecutive alarming results as one anomaly, ended by the next quiet result", () => {
    const results = [5, 1, 2, 3, 4, 6].map(time => ({ time, alarm: time !== 3 && time !== 6 }));
    expect(alarmSpans(results)).toEqual([[1, 2], [4, 5]]);
  });

  it("draws anomalies that touch as one shape and stripes the stretch monitors share", () => {
    const pills = buildStripPills([row("a", [[100, 300]]), row("b", [[250, 400]]), row("c", [[800, 800]])], [0, 1000], 1000);
    expect(pills).toHaveLength(2);
    expect(pills[0]!.parts.map(part => [part.a, part.b, names(part.members)])).toEqual([
      [93, 243, ["a"]], [243, 307, ["a", "b"]], [307, 407, ["b"]]]);
    // One result is still wide enough to see and to press.
    expect(pills[1]).toMatchObject({ left: 800 - STRIP.minHalf, right: 800 + STRIP.minHalf });
    expect(buildStripPills([row("a", [[5, 6]])], [10, 20], 1000)).toEqual([]);
  });

  it("joins neighbouring shared stretches into one block that names each monitor once", () => {
    const pills = buildStripPills([row("a", [[100, 200]]), row("b", [[150, 300]]), row("c", [[190, 250]])], [0, 1000], 1000);
    const shared = pills[0]!.parts.filter(part => part.members.length > 1);
    expect(shared.map(part => names(part.members))).toEqual([["a", "b"], ["a", "b", "c"], ["b", "c"], ["b"]].slice(0, shared.length));
    expect(new Set(shared.map(part => part.overlap)).size).toBe(1);
    expect(names(shared[0]!.overlap!.members)).toEqual(["a", "b", "c"]);
  });

  it("leaves the strip where it is until the lens is on, and keeps positions in order under it", () => {
    expect(lensOptics({ focus: 300, strength: 0 }, 1000).fish(310)).toBe(310);
    const { fish, bump } = lensOptics({ focus: 300, strength: 1 }, 1000);
    const xs = Array.from({ length: 200 }, (_, step) => 200 + step);
    expect(xs.every((x, at) => at === 0 || fish(x) > fish(xs[at - 1]!))).toBe(true);
    expect(fish(310) - fish(300)).toBeGreaterThan(10);
    expect(fish(500)).toBe(500);
    expect(bump(300)).toBe(1);
    expect(bump(500)).toBe(0);
  });

  it("gives every monitor of a shared stretch an equal field wide enough to press, exactly where it is drawn", () => {
    const pills = buildStripPills([row("a", [[400, 420]]), row("b", [[400, 420]]), row("c", [[400, 420]])], [0, 1000], 1000);
    const lock = pills[0]!.parts[0]!.overlap!;
    const lens = { focus: (lock.a + lock.b) / 2, strength: 1, lock };
    const { fish } = lensOptics(lens, 1000);
    const left = fish(lock.a), each = (fish(lock.b) - left) / 3;
    expect(each).toBeGreaterThanOrEqual(STRIP.field - 0.01);
    for (const [field, id] of ["a", "b", "c"].entries()) for (const offset of [1, each / 2, each - 1]) {
      expect(locateOnStrip(pills, lens, 1000, left + field * each + offset)).toMatchObject({ slice: field, row: { id } });
    }
    expect(locateOnStrip(pills, lens, 1000, left - 20).row).toBeUndefined();
  });

  it("hands out five colours in the order of the monitors' ids, then starts over", () => {
    const colors = monitorColors(["m2", "m1", "m6", "m3", "m5", "m4"], false);
    expect(colors.get("m1")).toBe("#a86400");
    expect(colors.get("m6")).toBe(colors.get("m1"));
    expect(new Set(colors.values()).size).toBe(5);
    expect(monitorColors(["m1"], true).get("m1")).toBe("#fbbf24");
  });
});

describe("chart views", () => {
  const monitors = ["One", "Two", "Three", "Four"].map(name => ({ id: name.toLowerCase(), name, color: "#000" }));

  it("offers raw data first and one view per monitor, and nothing without a monitor", () => {
    const onChange = vi.fn();
    const { container, rerender } = render(<MonitorViews monitors={[]} value={RAW_VIEW} onChange={onChange} />);
    expect(container.innerHTML).toBe("");
    rerender(<MonitorViews monitors={monitors.slice(0, 2)} value="one" onChange={onChange} aimed="two" />);
    expect(screen.getAllByRole("button").map(button => button.textContent)).toEqual(["Raw data", "One", "Two"]);
    expect(screen.getByRole("button", { name: "One" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "Two" }).className).toBe("is-aimed");
    fireEvent.click(screen.getByRole("button", { name: "Raw data" }));
    expect(onChange).toHaveBeenCalledWith(RAW_VIEW);
  });

  it("becomes a list once there are more views than fit side by side", () => {
    const onChange = vi.fn();
    render(<MonitorViews monitors={monitors} value={RAW_VIEW} onChange={onChange} />);
    fireEvent.change(screen.getByRole("combobox", { name: "Chart view" }), { target: { value: "four" } });
    expect(onChange).toHaveBeenCalledWith("four");
  });
});
