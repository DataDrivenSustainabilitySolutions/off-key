import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  normalizeCatalog,
  normalizeDefinition,
  normalizeLayout,
  type PipelineValidation,
} from "@/features/pipelines/contracts";
import type { GraphDocument } from "@/features/pipelines/model";
import { useGraphEditor, useUnsavedChanges } from "@/features/pipelines/useGraphEditor";
import { clearNavigationDrafts, useNavigationDraft } from "@/lib/navigation-draft";

const initial: GraphDocument = {
  definition: normalizeDefinition({
    nodes: [{ id: "source", kind: "source", component: "source.aligned" }],
  }),
  layout: normalizeLayout({ nodes: { source: { x: 0, y: 0 } } }),
};
const components = normalizeCatalog({
  catalog_id: "test", authoring_enabled: true, templates: [], components: [{
    id: "transform.test", kind: "transform", label: "Transform", description: "",
    strategies: ["static_baseline"], input_type: "features", output_type: "features",
  }],
}).components;

function useEditor(readOnly = false) {
  const [document, setDocument] = useNavigationDraft("graph-test:document", initial);
  const editor = useGraphEditor({
    document, onChange: setDocument, components, readOnly, historyKey: "graph-test:history",
  });
  useUnsavedChanges(JSON.stringify(document) !== JSON.stringify(initial));
  return { ...editor, document };
}
const move = (document: GraphDocument, x: number): GraphDocument => ({
  ...document, layout: normalizeLayout({ nodes: { source: { x, y: 0 } } }),
});
function beforeUnload() {
  const event = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(event);
  return event.defaultPrevented;
}

beforeEach(clearNavigationDrafts);
afterEach(cleanup);

describe("shared graph editing controller", () => {
  it("retains layout undo, redo, and the unload guard through navigation", () => {
    const first = renderHook(() => useEditor());
    expect(beforeUnload()).toBe(false);
    act(() => first.result.current.commit(move(first.result.current.document, 75)));
    expect(beforeUnload()).toBe(true);
    first.unmount();

    const second = renderHook(() => useEditor());
    expect(second.result.current.document.layout.nodes.source?.x).toBe(75);
    expect(second.result.current.canUndo).toBe(true);
    expect(beforeUnload()).toBe(true);
    act(() => second.result.current.undo());
    expect(second.result.current.document).toEqual(initial);
    expect(beforeUnload()).toBe(false);
    second.unmount();

    const third = renderHook(() => useEditor());
    expect(third.result.current.canRedo).toBe(true);
    act(() => third.result.current.redo());
    expect(third.result.current.document.layout.nodes.source?.x).toBe(75);
    expect(beforeUnload()).toBe(true);
  });

  it("records a drag as one checkpoint and selects newly added components", () => {
    const hook = renderHook(() => useEditor());
    act(() => hook.result.current.beginMove());
    act(() => hook.result.current.commit(move(hook.result.current.document, 25), false));
    act(() => hook.result.current.commit(move(hook.result.current.document, 50), false));
    act(() => hook.result.current.undo());
    expect(hook.result.current.document).toEqual(initial);
    expect(hook.result.current.canUndo).toBe(false);
    act(() => hook.result.current.add("transform.test", { x: 100, y: 200 }));
    expect(hook.result.current.selected).toBe("transform_test_1");
    expect(hook.result.current.document.layout.nodes.transform_test_1).toMatchObject({ x: 100, y: 200 });
    expect(hook.result.current.canRedo).toBe(false);
  });

  it("drops a validation result when the definition changes during the request", async () => {
    const hook = renderHook(() => useEditor());
    let finish!: (result: PipelineValidation) => void;
    const request = vi.fn(() => new Promise<PipelineValidation>((resolve) => { finish = resolve; }));
    let pending!: ReturnType<typeof hook.result.current.validate>;
    act(() => { pending = hook.result.current.validate(request); });
    act(() => hook.result.current.add("transform.test"));
    await act(async () => {
      finish({ valid: true, definition: initial.definition, features: {}, issues: [] });
      expect(await pending).toBeUndefined();
    });
    expect(hook.result.current.validation).toBeUndefined();
  });

  it("keeps validation through layout changes and invalidates it on definition undo", async () => {
    const hook = renderHook(() => useEditor());
    act(() => hook.result.current.add("transform.test"));
    const report = { valid: true, definition: hook.result.current.document.definition, features: {}, issues: [] };
    await act(async () => { await hook.result.current.validate(async () => report); });
    act(() => hook.result.current.commit(move(hook.result.current.document, 75)));
    expect(hook.result.current.validation).toBe(report);
    act(() => hook.result.current.undo());
    expect(hook.result.current.validation).toBe(report);
    act(() => hook.result.current.undo());
    expect(hook.result.current.validation).toBeUndefined();
  });

  it("runs the real layout engine and discards arrangements after newer edits", async () => {
    const hook = renderHook(() => useEditor());
    let pending!: ReturnType<typeof hook.result.current.arrange>;
    act(() => { pending = hook.result.current.arrange(); });
    act(() => hook.result.current.commit(move(hook.result.current.document, 75)));
    await act(async () => { expect(await pending).toBe(false); });
    expect(hook.result.current.document.layout.nodes.source?.x).toBe(75);
    await act(async () => { expect(await hook.result.current.arrange()).toBe(true); });
    expect(hook.result.current.fitRequest).toBe(1);
    expect(hook.result.current.document.layout.nodes.source?.x).toBeTypeOf("number");
  });

  it("does not commit a layout after unmount or mutate read-only documents", async () => {
    const onChange = vi.fn();
    const hook = renderHook(() => useGraphEditor({ document: initial, onChange, components }));
    let pending!: ReturnType<typeof hook.result.current.arrange>;
    act(() => { pending = hook.result.current.arrange(); });
    hook.unmount();
    await act(async () => { expect(await pending).toBe(false); });
    expect(onChange).not.toHaveBeenCalled();

    const readOnly = renderHook(() => useEditor(true));
    act(() => {
      readOnly.result.current.beginMove();
      readOnly.result.current.add("transform.test");
      readOnly.result.current.commit(move(initial, 75));
    });
    expect(readOnly.result.current.document).toBe(initial);
    expect(readOnly.result.current.canUndo).toBe(false);
  });
});
