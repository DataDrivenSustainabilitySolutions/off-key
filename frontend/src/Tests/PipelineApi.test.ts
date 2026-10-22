import { beforeEach, describe, expect, it, vi } from "vitest";

import { pipelinesApi } from "@/features/pipelines/api";
import { apiUtils } from "@/lib/api-client";
import type { PipelineDefinition } from "@/types/pipelines.generated";

vi.mock("@/lib/api-client", () => ({
  apiUtils: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

const mockGet = vi.mocked(apiUtils.get);
const mockPost = vi.mocked(apiUtils.post);
const mockPut = vi.mocked(apiUtils.put);
const mockPatch = vi.mocked(apiUtils.patch);
const mockDelete = vi.mocked(apiUtils.delete);

const signal = new AbortController().signal;
const optional = { signal, redirectOnUnauthorized: false };
const definition: PipelineDefinition = {
  nodes: [{ id: "input", kind: "source", component: "source.aligned" }],
};
/** What the normalizers make of `definition`: every omitted field gets its default. */
const normalized = {
  strategy: "static_baseline",
  input_slots: [],
  nodes: [
    { id: "input", kind: "source", component: "source.aligned", params: {} },
  ],
  edges: [],
  settings: {
    training_window_size: 1200,
    calibration_window_size: 360,
    seed: 42,
    conformal_strategy: "split",
  },
};
/** Satisfies every normalizer, so the routing rows can share one response. */
const wire = { draft: definition, definition, components: [], templates: [] };

const reads: Array<[string, () => Promise<unknown>, string, object]> = [
  [
    "catalog",
    () => pipelinesApi.catalog(signal),
    "/v1/monitors/pipelines/catalog",
    optional,
  ],
  [
    "list",
    () => pipelinesApi.list({ limit: 5 }, signal),
    "/v1/monitors/pipelines",
    { ...optional, params: { limit: 5 } },
  ],
  [
    "get",
    () => pipelinesApi.get("line/1", signal),
    "/v1/monitors/pipelines/line%2F1",
    optional,
  ],
  [
    "revision",
    () => pipelinesApi.revision("line/1", "rev 2", signal),
    "/v1/monitors/pipelines/line%2F1/revisions/rev%202",
    optional,
  ],
  [
    "service",
    () => pipelinesApi.service("svc/1", signal),
    "/v1/monitors/svc%2F1/pipeline",
    { ...optional, params: undefined },
  ],
  [
    "service for a selected node",
    () => pipelinesApi.service("svc/1", signal, "node"),
    "/v1/monitors/svc%2F1/pipeline",
    { ...optional, params: { selected_node_id: "node" } },
  ],
  [
    "history",
    () => pipelinesApi.history("svc/1", signal),
    "/v1/monitors/svc%2F1/pipeline-history",
    optional,
  ],
  [
    "runMetadata",
    () => pipelinesApi.runMetadata("svc/1", definition, "node", signal),
    "/v1/monitors/svc%2F1/pipeline-metadata",
    { ...optional, params: { selected_node_id: "node" } },
  ],
  [
    "activation",
    () => pipelinesApi.activation("op/1", signal),
    "/v1/monitors/pipeline-activations/op%2F1",
    optional,
  ],
];

describe("pipelines API", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    for (const mock of [mockGet, mockPost, mockPut, mockPatch, mockDelete]) {
      mock.mockResolvedValue(wire);
    }
  });

  it.each(reads)(
    "%s reads its encoded route and shows a sign-in state instead of redirecting",
    async (_, read, url, options) => {
      await read();

      expect(mockGet).toHaveBeenCalledExactlyOnceWith(url, options);
    },
  );

  it("sends writes to their encoded routes with the caller's payload", async () => {
    const request = { expected_version: 1, definition };

    await pipelinesApi.apply({ service_id: "svc" } as never);
    await pipelinesApi.create({ name: "Line", definition });
    await pipelinesApi.save("line/1", request);
    await pipelinesApi.metadata("line/1", { name: "Renamed" } as never);
    await pipelinesApi.saveLayout("svc/1", { nodes: {} });
    await pipelinesApi.activate({ service_id: "svc" } as never);
    await pipelinesApi.cancel("op/1");

    expect(mockPost.mock.calls).toEqual([
      ["/v1/monitors/pipelines/apply", { service_id: "svc" }],
      ["/v1/monitors/pipelines", { name: "Line", definition }],
      ["/v1/monitors/pipeline-activations", { service_id: "svc" }],
    ]);
    expect(mockPut.mock.calls).toEqual([
      ["/v1/monitors/pipelines/line%2F1/draft", request],
      ["/v1/monitors/svc%2F1/pipeline-layout", { nodes: {} }],
    ]);
    expect(mockPatch).toHaveBeenCalledExactlyOnceWith(
      "/v1/monitors/pipelines/line%2F1",
      { name: "Renamed" },
    );
    expect(mockDelete).toHaveBeenCalledExactlyOnceWith(
      "/v1/monitors/pipeline-activations/op%2F1",
    );
  });

  it("validates a draft and falls back to the submitted definition", async () => {
    mockPost.mockResolvedValueOnce({ valid: true, definition: null });

    const report = await pipelinesApi.validate(definition, signal, "node");

    expect(mockPost).toHaveBeenCalledExactlyOnceWith(
      "/v1/monitors/pipelines/validate",
      { definition, selected_node_id: "node" },
      { signal },
    );
    expect(report).toEqual({
      valid: true,
      definition: normalized,
      features: {},
      issues: [],
    });
  });

  it("normalizes designs, revisions, templates and running services", async () => {
    const layout = { nodes: { input: { x: 1, y: 2 } } };
    mockGet
      .mockResolvedValueOnce({ id: "line", draft: definition })
      .mockResolvedValueOnce({ id: "rev", definition })
      .mockResolvedValueOnce({
        catalog_id: "catalog",
        components: [{ id: "source.aligned", kind: "source" }],
        templates: [{ id: "starter", definition, layout }],
      })
      .mockResolvedValueOnce({ definition, validation: { valid: false } })
      .mockResolvedValueOnce({ definition, layout, validation: null });

    await expect(pipelinesApi.get("line")).resolves.toEqual({
      id: "line",
      draft: normalized,
      layout: { nodes: {} },
      revisions: [],
    });
    await expect(pipelinesApi.revision("line", "rev")).resolves.toEqual({
      id: "rev",
      definition: normalized,
    });
    await expect(pipelinesApi.catalog()).resolves.toEqual({
      catalog_id: "catalog",
      components: [{ id: "source.aligned", kind: "source", fields: [] }],
      templates: [{ id: "starter", definition: normalized, layout }],
    });
    await expect(pipelinesApi.service("svc")).resolves.toEqual({
      definition: normalized,
      layout: { nodes: {} },
      validation: {
        valid: false,
        definition: normalized,
        features: {},
        issues: [],
      },
    });
    await expect(pipelinesApi.service("svc")).resolves.toEqual({
      definition: normalized,
      layout,
      validation: null,
    });
  });
});
