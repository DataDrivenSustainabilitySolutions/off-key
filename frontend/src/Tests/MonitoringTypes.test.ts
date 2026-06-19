import { describe, expect, it } from "vitest";

import { getStatusDisplay } from "../types/monitoring";

describe("monitoring status display", () => {
  it("shows exited workloads as neutral until exit codes are available", () => {
    const status = getStatusDisplay("exited", true);

    expect(status.label).toBe("Exited");
    expect(status.className).toContain("yellow");
  });

  it("shows restarting workloads as transient", () => {
    const status = getStatusDisplay("restarting", true);

    expect(status.label).toBe("Restarting");
    expect(status.className).toContain("yellow");
  });

  it("shows explicitly stopped workloads as stopped", () => {
    const status = getStatusDisplay("stopped", false);

    expect(status.label).toBe("Stopped");
    expect(status.className).toContain("gray");
  });
});
