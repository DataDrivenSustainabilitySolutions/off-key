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
