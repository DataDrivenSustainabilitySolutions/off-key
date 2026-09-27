import { AxiosError } from "axios";
import { expect, it } from "vitest";
import { apiClient } from "../lib/api-client";

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
    await expect(client.post("/v1/sources/preview", {})).rejects.toThrow(
      "catalog.sources.0.host: Use a broker hostname, without a URL or port",
    );
  } finally {
    client.defaults.adapter = original;
  }
});
