// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { apiUtils } from "@/lib/api-client";
import { startFormMonitor } from "@/features/monitoring/setup/startMonitor";
import type { MonitorSetup } from "@/types/monitoring";

vi.mock("@/lib/api-client", () => ({ apiUtils: { get: vi.fn(), post: vi.fn() } }));

const request = { display_name: "radar", reading_ids: ["L1"] } as MonitorSetup;
const activation = (phase: string, error: string | null = null) => ({ id: "activation", monitor_id: "service", phase, error });

afterEach(() => vi.resetAllMocks());

describe("form monitor start", () => {
  it("waits until the activation has created the service", async () => {
    vi.mocked(apiUtils.post).mockResolvedValue({ monitor_id: "service", activation_id: "activation" });
    vi.mocked(apiUtils.get)
      .mockResolvedValueOnce(activation("requested"))
      .mockResolvedValueOnce(activation("starting"))
      .mockResolvedValueOnce(activation("awaiting_heartbeat"));
    await expect(startFormMonitor(request, 0)).resolves.toBe("service");
    expect(apiUtils.get).toHaveBeenCalledTimes(3);
  });

  it.each([
    ["failed", "Detector parameters rejected", "Detector parameters rejected"],
    ["cancelled", null, "Monitoring start was cancelled"],
  ])("reports a %s activation", async (phase, error, message) => {
    vi.mocked(apiUtils.post).mockResolvedValue({ monitor_id: "service", activation_id: "activation" });
    vi.mocked(apiUtils.get).mockResolvedValue(activation(phase, error));
    await expect(startFormMonitor(request, 0)).rejects.toThrow(message);
  });
});
