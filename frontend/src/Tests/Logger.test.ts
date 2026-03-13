import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  clientLogger,
  setClientLoggerProductionOverride,
} from "@/lib/logger";

const CURRENT_DIR = path.dirname(fileURLToPath(import.meta.url));
const SRC_ROOT = path.resolve(CURRENT_DIR, "..");

const collectSourceFiles = (dirPath: string): string[] => {
  const entries = fs.readdirSync(dirPath, { withFileTypes: true });
  const files: string[] = [];

  for (const entry of entries) {
    const fullPath = path.join(dirPath, entry.name);

    if (entry.isDirectory()) {
      if (entry.name === "Tests") {
        continue;
      }
      files.push(...collectSourceFiles(fullPath));
      continue;
    }

    if (!/\.(ts|tsx)$/.test(entry.name)) {
      continue;
    }
    if (fullPath.endsWith(path.join("lib", "logger.ts"))) {
      continue;
    }
    files.push(fullPath);
  }

  return files;
};

afterEach(() => {
  vi.restoreAllMocks();
  setClientLoggerProductionOverride(null);
});

describe("clientLogger", () => {
  it("suppresses debug/info in production mode", () => {
    setClientLoggerProductionOverride(true);
    const infoSpy = vi.spyOn(console, "info").mockImplementation(() => undefined);
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => undefined);

    clientLogger.info({ event: "log.info" });
    clientLogger.warn({ event: "log.warn" });
    clientLogger.error({ event: "log.error" });

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
    const payload = errorSpy.mock.calls[0][0] as Record<string, unknown>;
    expect(payload.event).toBe("ui.fetch_failed");
    expect(payload.message).toBe("Request failed");
    expect(payload.correlationId).toBe("cid-123");
    expect(payload.requestId).toBe("rid-123");
    expect(payload.context).toEqual({ endpoint: "/v1/test" });

    const serializedError = payload.error as Record<string, unknown>;
    expect(serializedError.name).toBe("Error");
    expect(serializedError.message).toBe("failed");
  });

  it("avoids direct console usage outside logger wrapper", () => {
    const files = collectSourceFiles(SRC_ROOT);
    const offenders: string[] = [];
    const consoleCall = /\bconsole\.(debug|info|warn|error|log)\s*\(/;

    for (const filePath of files) {
      const content = fs.readFileSync(filePath, "utf8");
      if (consoleCall.test(content)) {
        offenders.push(path.relative(SRC_ROOT, filePath));
      }
    }

    expect(offenders).toEqual([]);
  });
});
