import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiRequestError, apiClient, apiUtils } from "@/lib/api-client";
import { createEmptySystem } from "@/features/spatial/systemDocument";
import { useSystemDocument } from "@/features/spatial/useSystemDocument";
import type {
  SystemDocument,
  SystemSnapshot,
} from "@/features/spatial/systemTypes";

vi.mock("@/lib/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-client")>();
  return {
    ...actual,
    apiUtils: { ...actual.apiUtils, get: vi.fn() },
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
    legacy_collection_revision: 0,
    message: "Saved configuration",
  },
});
const acknowledgement = (value: SystemSnapshot) => ({ data: value });

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
