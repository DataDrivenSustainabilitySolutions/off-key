// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  clientLogger,
  setClientLoggerProductionOverride,
} from "@/lib/logger";

afterEach(() => {
  setClientLoggerProductionOverride(null);
});

describe("clientLogger", () => {
  it("suppresses debug/info in production mode", () => {
    setClientLoggerProductionOverride(true);
    const debugSpy = vi.spyOn(console, "debug").mockImplementation(() => undefined);
    const infoSpy = vi.spyOn(console, "info").mockImplementation(() => undefined);
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => undefined);

    clientLogger.debug({ event: "log.debug" });
    clientLogger.info({ event: "log.info" });
    clientLogger.warn({ event: "log.warn" });
    clientLogger.error({ event: "log.error" });

    expect(debugSpy).not.toHaveBeenCalled();
    expect(infoSpy).not.toHaveBeenCalled();
    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(errorSpy).toHaveBeenCalledTimes(1);
  });

  it("emits structured error payload", () => {
    setClientLoggerProductionOverride(false);
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const failure = new Error("failed");

    clientLogger.error({
      event: "ui.fetch_failed",
      message: "Request failed",
      context: { endpoint: "/v1/test" },
      correlationId: "cid-123",
      requestId: "rid-123",
      error: failure,
    });

    expect(errorSpy).toHaveBeenCalledTimes(1);
    const payload = errorSpy.mock.calls[0]?.[0] as
      | Record<string, unknown>
      | undefined;
    expect(payload).toBeDefined();
    if (!payload) throw new Error("Expected a structured client log payload");
    expect(payload.event).toBe("ui.fetch_failed");
    expect(payload.message).toBe("Request failed");
    expect(payload.correlationId).toBe("cid-123");
    expect(payload.requestId).toBe("rid-123");
    expect(payload.context).toEqual({ endpoint: "/v1/test" });

    const serializedError = payload.error as Record<string, unknown>;
    expect(serializedError.name).toBe("Error");
    expect(serializedError.message).toBe("failed");
  });
});
