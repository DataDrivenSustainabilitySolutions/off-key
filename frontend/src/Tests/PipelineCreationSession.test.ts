// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";
import { pipelinesApi } from "@/features/pipelines/api";
import { normalizeDefinition, normalizeLayout, normalizeView } from "@/features/pipelines/contracts";
import { createCreationSession, type CreationDraft } from "@/features/pipelines/creationSession";
import { isDraftDirty } from "@/features/pipelines/editorSession";
import { clearNavigationDrafts, navigationDraft } from "@/lib/navigation-draft";

vi.mock("@/features/pipelines/api", () => ({ pipelinesApi: { create: vi.fn(), save: vi.fn() } }));

const initial = (): CreationDraft => ({
  document: { definition: normalizeDefinition({}), layout: normalizeLayout() },
  name: "",
  description: "",
  startingId: "adaptive",
  targetId: "room",
});
const saved = () => normalizeView({
  id: "created-design", name: "Machine health", description: "", version: 1,
  archived: false, draft: normalizeDefinition({}), layout: normalizeLayout(),
  revisions: [], created_at: "2026-10-17T12:00:00Z", updated_at: "2026-10-17T12:00:00Z",
});

beforeEach(() => { vi.resetAllMocks(); clearNavigationDrafts(); });

describe("account-scoped pipeline creation session", () => {
  it("restores a reading selection even when the unnamed graph did not change", () => {
    const session = createCreationSession(initial(), "creation:bindings");
    session.setDraft((draft) => ({ ...draft, targetId: "other-room", bindings: { value: "other-current" } }));
    expect(session.isDirty()).toBe(true);
    const restored = createCreationSession(initial(), "creation:bindings");
    expect(restored.getSnapshot().draft.targetId).toBe("other-room");
    expect(restored.getSnapshot().draft.bindings).toEqual({ value: "other-current" });
  });
  it("retains the dirty baseline across navigation, independently of template provenance", () => {
    const open = () => navigationDraft("creation:1", () => createCreationSession(initial()));
    const first = open();
    first.setDraft((draft) => ({ ...draft, document: { ...draft.document,
      layout: normalizeLayout({ nodes: { input: { x: 32, y: 48 } } }),
    } }));

    const { draft, baseline } = open().getSnapshot();
    expect(draft.name).toBe("");
    expect(draft.startingId).toBe("adaptive");
    expect(isDraftDirty(draft, baseline)).toBe(true);
    first.setDraft(baseline);
    expect(isDraftDirty(first.getSnapshot().draft, first.getSnapshot().baseline)).toBe(false);
  });

  it("acknowledges one real save operation even with no screen subscribed", async () => {
    let acknowledge!: (value: ReturnType<typeof saved>) => void;
    vi.mocked(pipelinesApi.create).mockImplementation(() => new Promise((resolve) => { acknowledge = resolve; }));
    const session = createCreationSession({ ...initial(), name: "Machine health" });
    const listener = vi.fn();
    const unsubscribe = session.subscribe(listener);
    const pending = session.save();
    unsubscribe();
    listener.mockClear();
    await session.save();
    session.setDraft((draft) => ({ ...draft, name: "Edited while away", document: {
      ...draft.document, layout: normalizeLayout({ nodes: { input: { x: 32, y: 48, label: "New title" } } }),
    } }));
    acknowledge(saved());
    await pending;

    expect(listener).not.toHaveBeenCalled();
    expect(session.getSnapshot().save.status).toBe("saved");
    await session.save();
    expect(pipelinesApi.create).toHaveBeenCalledOnce();
    expect(session.getSnapshot().template?.id).toBe("created-design");
    expect(session.getSnapshot().draft.name).toBe("Edited while away");
    expect(session.getSnapshot().draft.document.layout.nodes.input?.label).toBe("New title");
    expect(session.getSnapshot().draft.targetId).toBe("room");
    expect(session.isDirty()).toBe(true);
    session.acknowledge();
    vi.mocked(pipelinesApi.save).mockResolvedValue({ ...saved(), version: 2 });
    await session.save();
    expect(pipelinesApi.create).toHaveBeenCalledOnce();
    expect(pipelinesApi.save).toHaveBeenCalledWith("created-design", expect.objectContaining({ expected_version: 1 }));
  });

  it("shows failed saves after remount and permits a deliberate retry", async () => {
    vi.mocked(pipelinesApi.create).mockRejectedValueOnce(new Error("Service unavailable"));
    const session = createCreationSession({ ...initial(), name: "Machine health" });
    await session.save();
    expect(session.getSnapshot().save).toEqual({ status: "error", message: "Service unavailable", conflict: false });
    vi.mocked(pipelinesApi.create).mockResolvedValueOnce(saved());
    await session.save();
    expect(session.getSnapshot().save.status).toBe("saved");
    expect(pipelinesApi.create).toHaveBeenCalledTimes(2);
  });

  it("does not resurrect an account's navigation state after logout", async () => {
    let acknowledge!: (value: ReturnType<typeof saved>) => void;
    vi.mocked(pipelinesApi.create).mockImplementation(() => new Promise((resolve) => { acknowledge = resolve; }));
    const first = navigationDraft("creation:1", () => createCreationSession({ ...initial(), name: "Machine health" }));
    const pending = first.save();
    clearNavigationDrafts();
    acknowledge(saved());
    await pending;
    const next = navigationDraft("creation:1", () => createCreationSession(initial()));
    expect(next).not.toBe(first);
    expect(next.getSnapshot().save.status).toBe("idle");
    expect(next.getSnapshot().draft.name).toBe("");
  });
});
