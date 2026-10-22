import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiRequestError, apiClient, apiUtils } from "@/lib/api-client";
import { createEmptySystem } from "@/features/catalogue/systemDocument";
import { useSystemDocument } from "@/features/catalogue/useSystemDocument";
import type {
  SystemDocument,
  SystemSnapshot,
} from "@/features/catalogue/systemTypes";

vi.mock("@/lib/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-client")>();
  return {
    ...actual,
    apiUtils: { ...actual.apiUtils, get: vi.fn(), post: vi.fn() },
    apiClient: { ...actual.apiClient, put: vi.fn() },
  };
});

const document = (label = "Original device"): SystemDocument => ({
  ...createEmptySystem(),
  devices: [{ id: "device", label, kind: "device" }],
});
const snapshot = (
  revision = 1,
  label = "Original device",
  canEdit = true,
): SystemSnapshot => ({
  revision,
  document: document(label),
  can_edit: canEdit,
  storage_origin: "saved",
  runtime: {
    mode: "configured_only",
    message: "Saved configuration",
  },
});
const acknowledgement = (value: SystemSnapshot) => ({ data: value });

const runtimeSnapshot = (status = "applied", revision = 1): SystemSnapshot => ({
  ...snapshot(revision),
  document: { ...document(),
    connections: ["broker", "other"].map(id => ({ id, label: id, protocol: "mqtt", host: `${id}.example.test`, port: 1883, transport: "tcp", tls: false })),
    streams: ["temperature", "humidity"].map((id, position) => ({ id, label: id, connection_id: position ? "other" : "broker", topic: `weather/${id}`, value_type: "number", category: "Environment" })),
  },
  runtime: {
    mode: "collection", message: "Recording", collection_revision: 2, collection: { revision: 2, status },
    bindings: Object.fromEntries(["temperature", "humidity"].map((id, position) => [id, {
      connection_id: position ? "other" : "broker", entity_id: "device", telemetry_key: id,
      accepted_topic: `telemetry/device/${id}`, policy: { mode: "sample", interval_seconds: 10 },
    }])),
    ingress: { sources: { broker: { state: "connected" }, other: { state: "connected" } } },
    latest_readings: { humidity: { value: 40, received_at: "2026-10-13T09:00:00Z", is_snapshot: false } },
  },
});
type RuntimeResponse = Pick<SystemSnapshot, "revision" | "runtime">;
function runtimeTimers() {
  vi.spyOn(globalThis.document, "hidden", "get").mockReturnValue(false);
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
}
async function advanceRuntime(milliseconds: number) {
  await act(async () => { await vi.advanceTimersByTimeAsync(milliseconds); });
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("saved system persistence", () => {
  it("does not request or write saved systems for anonymous previews", async () => {
    const { result } = renderHook(() =>
      useSystemDocument({ isAuthenticated: false }),
    );
    expect(result.current.status).toBe("sign-in-required");
    await act(async () => {
      expect(await result.current.save(document())).toBe(false);
    });
    expect(apiUtils.get).not.toHaveBeenCalled();
    expect(apiClient.put).not.toHaveBeenCalled();
  });

  it("loads viewer configurations without granting write permission", async () => {
    vi.mocked(apiUtils.get).mockResolvedValue(
      snapshot(2, "Viewer device", false),
    );
    const { result } = renderHook(() =>
      useSystemDocument({ isAuthenticated: true, accountKey: 1 }),
    );
    await waitFor(() => expect(result.current.status).toBe("read-only"));
    expect(result.current.document?.devices[0]?.label).toBe("Viewer device");
    await act(async () => {
      expect(await result.current.save(document("Unauthorized"))).toBe(false);
    });
    expect(apiClient.put).not.toHaveBeenCalled();
  });

  it("sends the full configuration and expected revision, then updates titles only on acknowledgement", async () => {
    vi.mocked(apiUtils.get).mockResolvedValue(snapshot());
    let resolve!: (value: ReturnType<typeof acknowledgement>) => void;
    vi.mocked(apiClient.put).mockImplementation(
      () =>
        new Promise((ack) => {
          resolve = ack;
        }),
    );
    const onDocument = vi.fn();
    const { result } = renderHook(() =>
      useSystemDocument({ isAuthenticated: true, accountKey: 1, onDocument }),
    );
    await waitFor(() => expect(result.current.canEdit).toBe(true));
    let pending!: Promise<boolean>;
    act(() => {
      pending = result.current.rename("device", "device", " Saved name ");
    });
    expect(result.current.saving).toBe(true);
    expect(result.current.document?.devices[0]?.label).toBe("Original device");
    expect(apiClient.put).toHaveBeenCalledWith(
      "/v1/system",
      { expected_revision: 1, document: document("Saved name") },
      expect.objectContaining({ redirectOnUnauthorized: false }),
    );
    await act(async () => {
      expect(await result.current.save(document("Second"))).toBe(false);
    });
    expect(apiClient.put).toHaveBeenCalledTimes(1);
    await act(async () => {
      resolve(acknowledgement(snapshot(2, "Saved name")));
      expect(await pending).toBe(true);
    });
    expect(result.current.document?.devices[0]?.label).toBe("Saved name");
    expect(onDocument).toHaveBeenCalledTimes(2);
    expect(result.current.revision).toBe(2);
  });

  it("refreshes on CAS conflicts but refuses to overwrite the newer revision with an old draft", async () => {
    vi.mocked(apiUtils.get)
      .mockResolvedValueOnce(snapshot())
      .mockResolvedValueOnce(snapshot(3, "Other editor"));
    vi.mocked(apiClient.put).mockRejectedValue(
      new ApiRequestError("Revision conflict", 409),
    );
    const { result } = renderHook(() =>
      useSystemDocument({ isAuthenticated: true }),
    );
    await waitFor(() => expect(result.current.canEdit).toBe(true));
    const draft = document("My unsaved change");
    await act(async () => {
      expect(await result.current.save(draft, 1)).toBe(false);
    });
    expect(result.current.document?.devices[0]?.label).toBe("Other editor");
    expect(result.current.error).toContain("Your draft has not been saved");
    await act(async () => {
      expect(await result.current.save(draft, 1)).toBe(false);
    });
    expect(apiClient.put).toHaveBeenCalledTimes(1);
    expect(draft.devices[0]?.label).toBe("My unsaved change");
  });

  it("keeps canonical names when the database cannot save", async () => {
    vi.mocked(apiUtils.get).mockResolvedValue(snapshot());
    vi.mocked(apiClient.put).mockRejectedValue(
      new ApiRequestError("Database unavailable", 503),
    );
    const { result } = renderHook(() =>
      useSystemDocument({ isAuthenticated: true }),
    );
    await waitFor(() => expect(result.current.canEdit).toBe(true));
    await act(async () => {
      expect(await result.current.save(document("Unsaved"))).toBe(false);
    });
    expect(result.current.document?.devices[0]?.label).toBe("Original device");
    expect(result.current.error).toBe("Database unavailable");
  });

  it("cancels and ignores delayed responses from the previous account", async () => {
    let resolveOld!: (value: SystemSnapshot) => void;
    vi.mocked(apiUtils.get)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveOld = resolve;
          }),
      )
      .mockResolvedValueOnce(snapshot(2, "Current account", false));
    const onDocument = vi.fn();
    const { result, rerender } = renderHook(
      ({ accountKey }) =>
        useSystemDocument({ isAuthenticated: true, accountKey, onDocument }),
      { initialProps: { accountKey: 1 } },
    );
    rerender({ accountKey: 2 });
    await waitFor(() =>
      expect(result.current.document?.devices[0]?.label).toBe(
        "Current account",
      ),
    );
    await act(async () => {
      resolveOld(snapshot(99, "Old account", true));
    });
    expect(result.current.document?.devices[0]?.label).toBe("Current account");
    expect(result.current.canEdit).toBe(false);
    expect(onDocument).toHaveBeenCalledTimes(1);
  });

  it("does not restore old write permission when a delayed save overlaps a role refresh", async () => {
    vi.mocked(apiUtils.get)
      .mockResolvedValueOnce(snapshot())
      .mockResolvedValueOnce(snapshot(1, "Original device", false));
    let resolve!: (value: ReturnType<typeof acknowledgement>) => void;
    vi.mocked(apiClient.put).mockImplementation(
      () =>
        new Promise((ack) => {
          resolve = ack;
        }),
    );
    const { result } = renderHook(() =>
      useSystemDocument({ isAuthenticated: true }),
    );
    await waitFor(() => expect(result.current.canEdit).toBe(true));
    let pending!: Promise<boolean>;
    act(() => {
      pending = result.current.save(document("Saved before role change"));
    });
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.canEdit).toBe(false);
    await act(async () => {
      resolve(acknowledgement(snapshot(2, "Saved before role change", true)));
      expect(await pending).toBe(true);
    });
    expect(result.current.canEdit).toBe(false);
    expect(result.current.status).toBe("read-only");
  });
});

describe("canonical system runtime polling", () => {
  it("follows worker acknowledgement and returns to a quiet poll interval", async () => {
    runtimeTimers();
    vi.mocked(apiUtils.get).mockResolvedValue(runtimeSnapshot("applying"));
    vi.mocked(apiUtils.post).mockResolvedValue(runtimeSnapshot("applied"));
    const { result } = renderHook(() => useSystemDocument({ isAuthenticated: true, accountKey: 1 }));
    await act(async () => {});
    expect(result.current.status).toBe("ready");
    await advanceRuntime(1999);
    expect(apiUtils.post).not.toHaveBeenCalled();
    await advanceRuntime(1);
    expect(result.current.snapshot?.runtime.collection?.status).toBe("applied");
    await advanceRuntime(4999);
    expect(apiUtils.post).toHaveBeenCalledOnce();
    await advanceRuntime(1);
    expect(apiUtils.post).toHaveBeenCalledTimes(2);
  });

  it.each(["broker", undefined])("removes stopped subscriptions with runtime scope %s", async runtimeConnectionId => {
    runtimeTimers();
    const saved = runtimeSnapshot();
    const next: RuntimeResponse = { revision: saved.revision, runtime: { ...saved.runtime,
      bindings: { temperature: { ...saved.runtime.bindings!.temperature!, policy: { mode: "off", interval_seconds: 10 } } },
      ingress: { sources: {} }, latest_readings: {},
    } };
    vi.mocked(apiUtils.get).mockResolvedValue(saved);
    vi.mocked(apiUtils.post).mockResolvedValue(next);
    const { result } = renderHook(() => useSystemDocument({ isAuthenticated: true, runtimeConnectionId }));
    await act(async () => {});
    expect(result.current.status).toBe("ready");
    await advanceRuntime(5000);
    expect(apiUtils.post).toHaveBeenCalledWith("/v1/system/collection/status", { stream_ids: runtimeConnectionId ? ["temperature"] : ["temperature", "humidity"] }, expect.anything());
    expect(result.current.snapshot?.runtime.ingress?.sources).toEqual(runtimeConnectionId ? { other: { state: "connected" } } : {});
    expect(result.current.snapshot?.runtime.bindings?.humidity).toEqual(saved.runtime.bindings?.humidity);
    expect(result.current.snapshot?.runtime.latest_readings?.humidity).toEqual(saved.runtime.latest_readings?.humidity);
  });

  it("aborts hidden requests, ignores late replies and refreshes immediately on resume", async () => {
    runtimeTimers();
    vi.mocked(apiUtils.get).mockResolvedValue(runtimeSnapshot("applying"));
    let resolveOld!: (value: RuntimeResponse) => void;
    vi.mocked(apiUtils.post).mockReturnValueOnce(new Promise<RuntimeResponse>(resolve => { resolveOld = resolve; })).mockResolvedValue(runtimeSnapshot("applied"));
    const { result } = renderHook(() => useSystemDocument({ isAuthenticated: true }));
    await act(async () => {});
    expect(result.current.status).toBe("ready");
    await advanceRuntime(2000);
    const signal = vi.mocked(apiUtils.post).mock.calls[0]![2]!.signal!;
    vi.spyOn(globalThis.document, "hidden", "get").mockReturnValue(true);
    act(() => globalThis.document.dispatchEvent(new Event("visibilitychange")));
    expect(signal.aborted).toBe(true);
    await advanceRuntime(20_000);
    expect(apiUtils.post).toHaveBeenCalledOnce();
    await act(async () => { resolveOld(runtimeSnapshot("applied")); });
    expect(result.current.snapshot?.runtime.collection?.status).toBe("applying");
    vi.spyOn(globalThis.document, "hidden", "get").mockReturnValue(false);
    await act(async () => { globalThis.document.dispatchEvent(new Event("visibilitychange")); });
    expect(apiUtils.post).toHaveBeenCalledTimes(2);
    expect(result.current.snapshot?.runtime.collection?.status).toBe("applied");
  });

  it("aborts polling on account changes and unmount without accepting old-account runtime", async () => {
    runtimeTimers();
    vi.mocked(apiUtils.get).mockResolvedValueOnce(runtimeSnapshot("applying")).mockResolvedValueOnce(runtimeSnapshot("applied"));
    let resolveOld!: (value: RuntimeResponse) => void;
    let resolveUnmounted!: (value: RuntimeResponse) => void;
    vi.mocked(apiUtils.post)
      .mockReturnValueOnce(new Promise<RuntimeResponse>(resolve => { resolveOld = resolve; }))
      .mockReturnValueOnce(new Promise<RuntimeResponse>(resolve => { resolveUnmounted = resolve; }));
    const { result, rerender, unmount } = renderHook(({ accountKey }) => useSystemDocument({ isAuthenticated: true, accountKey }), { initialProps: { accountKey: 1 } });
    await act(async () => {});
    expect(result.current.status).toBe("ready");
    await advanceRuntime(2000);
    const oldSignal = vi.mocked(apiUtils.post).mock.calls[0]![2]!.signal!;
    rerender({ accountKey: 2 });
    await act(async () => {});
    expect(result.current.snapshot?.runtime.collection?.status).toBe("applied");
    expect(oldSignal.aborted).toBe(true);
    await act(async () => { resolveOld(runtimeSnapshot("applying")); });
    expect(result.current.snapshot?.runtime.collection?.status).toBe("applied");
    await advanceRuntime(5000);
    const unmountedSignal = vi.mocked(apiUtils.post).mock.calls[1]![2]!.signal!;
    unmount();
    expect(unmountedSignal.aborted).toBe(true);
    await act(async () => { resolveUnmounted(runtimeSnapshot("applying")); });
    await advanceRuntime(20_000);
    expect(apiUtils.post).toHaveBeenCalledTimes(2);
  });

  it("invalidates a status reply when recording settings are saved", async () => {
    runtimeTimers();
    vi.mocked(apiUtils.get).mockResolvedValue(runtimeSnapshot());
    let resolveOld!: (value: RuntimeResponse) => void;
    vi.mocked(apiUtils.post).mockReturnValueOnce(new Promise<RuntimeResponse>(resolve => { resolveOld = resolve; }));
    const changed = runtimeSnapshot("applying");
    changed.runtime.collection_revision = 3;
    vi.mocked(apiClient.put).mockResolvedValue(acknowledgement(changed));
    const { result } = renderHook(() => useSystemDocument({ isAuthenticated: true }));
    await act(async () => {});
    expect(result.current.canEdit).toBe(true);
    await advanceRuntime(5000);
    const signal = vi.mocked(apiUtils.post).mock.calls[0]![2]!.signal!;
    await act(async () => {
      expect(await result.current.applyCollection({ expected_revision: 1, expected_collection_revision: 2,
        stream_ids: ["temperature"], policy: { mode: "original", interval_seconds: 10 } })).toBe(true);
    });
    expect(signal.aborted).toBe(true);
    const stale = runtimeSnapshot("applied");
    stale.runtime.collection_revision = 99;
    await act(async () => { resolveOld(stale); });
    expect(result.current.snapshot?.runtime.collection_revision).toBe(3);
    expect(result.current.snapshot?.runtime.collection?.status).toBe("applying");
  });

  it("refreshes the canonical catalogue when status reports another structure revision", async () => {
    runtimeTimers();
    const changed = runtimeSnapshot("applied", 3);
    changed.document.label = "Changed catalogue";
    vi.mocked(apiUtils.get).mockResolvedValueOnce(runtimeSnapshot()).mockResolvedValueOnce(changed);
    vi.mocked(apiUtils.post).mockResolvedValue({ revision: 3, runtime: changed.runtime });
    const { result } = renderHook(() => useSystemDocument({ isAuthenticated: true }));
    await act(async () => {});
    expect(result.current.status).toBe("ready");
    await advanceRuntime(5000);
    expect(result.current.revision).toBe(3);
    expect(result.current.document?.label).toBe("Changed catalogue");
    expect(apiUtils.get).toHaveBeenCalledTimes(2);
    expect(apiUtils.get).toHaveBeenLastCalledWith("/v1/system", expect.objectContaining({ signal: expect.any(AbortSignal), redirectOnUnauthorized: false }));
  });
});
