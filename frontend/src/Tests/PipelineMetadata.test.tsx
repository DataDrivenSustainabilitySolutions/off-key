import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  normalizeDefinition,
  normalizeLayout,
  normalizeValidation,
} from "@/features/pipelines/contracts";
import { pipelinesApi } from "@/features/pipelines/api";
import { useGraphMetadata } from "@/features/pipelines/useGraphMetadata";
import { useRunMetadata } from "@/features/pipelines/useRunMetadata";

vi.mock("@/features/pipelines/api", () => ({
  pipelinesApi: { validate: vi.fn(), service: vi.fn() },
}));
const definition = normalizeDefinition({
  strategy: "adaptive_stream",
  input_slots: [{ id: "value", label: "Value" }],
});
const report = (selected: string) =>
  normalizeValidation(
    {
      valid: true,
      definition,
      selected_node_id: selected,
      features: {
        [selected]: [{ name: `${selected}_component_1`, slots: [] }],
      },
      provenance_complete: false,
    },
    definition,
  );
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("bounded focused pipeline metadata", () => {
  it("retains the inspected graph when an oversized invalid definition echo is omitted", () => {
    const normalized = normalizeValidation(
      {
        valid: false,
        definition: null,
        definition_omitted: true,
        features: {},
      },
      definition,
    );
    expect(normalized.definition).toEqual(definition);
    expect(normalized.definition_omitted).toBe(true);
  });

  it("requests current selection context and discards late metadata for an earlier selection", async () => {
    vi.useFakeTimers();
    let finishFirst!: (value: ReturnType<typeof report>) => void;
    vi.mocked(pipelinesApi.validate)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finishFirst = resolve;
          }),
      )
      .mockResolvedValue(report("second"));
    const hook = renderHook(
      ({ selected }) => useGraphMetadata("design", definition, true, selected),
      { initialProps: { selected: "first" } },
    );
    await act(() => vi.advanceTimersByTimeAsync(800));
    expect(vi.mocked(pipelinesApi.validate).mock.calls[0]?.[3]).toBe("first");
    hook.rerender({ selected: "second" });
    await act(async () => finishFirst(report("first")));
    expect(hook.result.current).toBeUndefined();
    await act(() => vi.advanceTimersByTimeAsync(800));
    expect(hook.result.current?.selected_node_id).toBe("second");
    expect(hook.result.current?.features.second).toHaveLength(1);
  });

  it("keeps read-only metadata scoped to its run and inspected component", async () => {
    vi.useFakeTimers();
    let finishFirst!: (
      value: Awaited<ReturnType<typeof pipelinesApi.service>>,
    ) => void;
    const view = (selected: string) => ({
      run: null,
      history: [],
      definition,
      layout: normalizeLayout(),
      legacy: true,
      validation: report(selected),
    });
    vi.mocked(pipelinesApi.service)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finishFirst = resolve;
          }),
      )
      .mockResolvedValue(view("second"));
    const hook = renderHook(
      ({ selected }) => useRunMetadata("service", selected),
      { initialProps: { selected: "first" } },
    );
    await act(() => vi.advanceTimersByTimeAsync(200));
    hook.rerender({ selected: "second" });
    await act(async () => finishFirst(view("first")));
    expect(hook.result.current.validation).toBeUndefined();
    await act(() => vi.advanceTimersByTimeAsync(200));
    expect(vi.mocked(pipelinesApi.service).mock.calls[1]?.[2]).toBe("second");
    expect(hook.result.current.validation?.selected_node_id).toBe("second");
  });
});
