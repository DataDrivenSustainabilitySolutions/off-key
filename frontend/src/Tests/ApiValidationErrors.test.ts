import { AxiosError } from "axios";
import { expect, it } from "vitest";
import { ApiRequestError, apiClient, apiUtils, type ApiRequestOptions } from "../lib/api-client";

it("shows actionable field errors from catalog validation", async () => {
  const client = apiClient;
  const original = client.defaults.adapter;
  client.defaults.adapter = async (config) => {
    throw new AxiosError("Validation failed", "422", config, undefined, {
      status: 422,
      statusText: "Unprocessable Entity",
      headers: {},
      config,
      data: {
        detail: [
          {
            loc: ["body", "catalog", "sources", 0, "host"],
            msg: "Use a broker hostname, without a URL or port",
          },
        ],
      },
    });
  };
  try {
    await expect(client.post("/v1/system/collection/preview", {})).rejects.toMatchObject({
      status: 422,
      issues: [{ loc: ["body", "catalog", "sources", 0, "host"],
        msg: "Use a broker hostname, without a URL or port" }],
    });
    await expect(client.post("/v1/system/collection/preview", {})).rejects.toThrow(
      "catalog.sources.0.host: Use a broker hostname, without a URL or port",
    );
  } finally {
    client.defaults.adapter = original;
  }
});

it("preserves a conflict status for safe versioned catalog retries", async () => {
  const original = apiClient.defaults.adapter;
  apiClient.defaults.adapter = async (config) => {
    throw new AxiosError("Conflict", "409", config, undefined, {
      status: 409, statusText: "Conflict", headers: {}, config,
      data: { detail: "The catalog changed. Reload before editing." },
    });
  };
  try {
    await expect(apiClient.patch("/v1/system/labels", {})).rejects.toMatchObject({ name: "ApiRequestError", status: 409 });
    await expect(apiClient.patch("/v1/system/labels", {})).rejects.toBeInstanceOf(ApiRequestError);
  } finally { apiClient.defaults.adapter = original; }
});

it("lets optional preview requests surface an expired session without forcing navigation", async () => {
  const original = apiClient.defaults.adapter;
  apiClient.defaults.adapter = async (config) => {
    expect((config as typeof config & ApiRequestOptions).redirectOnUnauthorized).toBe(false);
    throw new AxiosError("Unauthorized", "401", config, undefined, {
      status: 401, statusText: "Unauthorized", headers: {}, config, data: { detail: "Login required" },
    });
  };
  try {
    await expect(apiUtils.get("/v1/system", { redirectOnUnauthorized: false })).rejects.toMatchObject({ name: "ApiRequestError", status: 401 });
  } finally { apiClient.defaults.adapter = original; }
});

it("names the server's reference on a server failure so it leads to its logs", async () => {
  const original = apiClient.defaults.adapter;
  apiClient.defaults.adapter = async (config) => {
    throw new AxiosError("Bad gateway", "502", config, undefined, {
      status: 502, statusText: "Bad Gateway", headers: { "x-correlation-id": "4f1c-9a" }, config,
      data: { detail: "Monitoring service is unavailable" },
    });
  };
  try {
    await expect(apiClient.get("/v1/monitors/overview")).rejects.toMatchObject({
      status: 502,
      reference: "4f1c-9a",
      message: "Monitoring service is unavailable (reference 4f1c-9a)",
    });
  } finally { apiClient.defaults.adapter = original; }
});

it("keeps client errors free of references and ignores unsafe header values", async () => {
  const original = apiClient.defaults.adapter;
  let status = 409;
  apiClient.defaults.adapter = async (config) => {
    throw new AxiosError("Failed", String(status), config, undefined, {
      status, statusText: "Failed", config,
      headers: { "x-correlation-id": status === 409 ? "4f1c-9a" : "<script>" },
      data: { detail: "Try again" },
    });
  };
  try {
    await expect(apiClient.get("/v1/system")).rejects.toMatchObject({ message: "Try again", reference: "4f1c-9a" });
    status = 503;
    await expect(apiClient.get("/v1/system")).rejects.toMatchObject({ message: "Try again", reference: undefined });
  } finally { apiClient.defaults.adapter = original; }
});
