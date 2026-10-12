import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AxiosError } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "@/auth/AuthContext";
import { ProtectedRoute } from "@/auth/ProtectedRoute";
import { endSession, refreshSession, tokenManager, waitForLogout } from "@/auth/session";
import { apiClient, apiUtils, ApiRequestError } from "@/lib/api-client";

const { getCurrentMember } = vi.hoisted(() => ({ getCurrentMember: vi.fn() }));
vi.mock("@/lib/member-api", () => ({ getCurrentMember }));

const member = { id: 42, email: "member@example.com", role: "user", is_active: true, is_verified: true };
const token = (seconds = 3600, label = "original") => `header.${btoa(JSON.stringify({ user_id: 42, exp: Math.floor(Date.now() / 1000) + seconds, label }))}.signature`;
const response = (accessToken: string) => new Response(JSON.stringify({ access_token: accessToken }), { status: 200 });
const fetchMock = vi.fn<typeof fetch>();
const originalAdapter = apiClient.defaults.adapter;

beforeEach(() => {
  tokenManager.removeToken();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  getCurrentMember.mockReset().mockResolvedValue(member);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  apiClient.defaults.adapter = originalAdapter;
  tokenManager.removeToken();
});

const Consumer = () => {
  const { isAuthenticated, member: profile, logout } = useAuth();
  return <><p>{isAuthenticated ? "signed in" : "signed out"}</p><p>{profile?.email}</p><button onClick={logout}>Logout</button></>;
};
const renderSession = () => render(<AuthProvider><MemoryRouter><ProtectedRoute><Consumer /></ProtectedRoute></MemoryRouter></AuthProvider>);

describe("remembered session recovery", () => {
  it("renews an expired saved token before rendering protected content", async () => {
    const renewed = token(3600, "renewed");
    tokenManager.setToken(token(-1), true);
    fetchMock.mockResolvedValueOnce(response(renewed));
    renderSession();
    expect(screen.getByText("Authentication is loading...")).toBeTruthy();
    expect(await screen.findByText(member.email)).toBeTruthy();
    expect(tokenManager.getToken()).toBe(renewed);
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ credentials: "include", headers: { "X-Off-Key-Session": "1" } });
  });

  it("keeps a saved login after a temporary profile failure and supports retry", async () => {
    const saved = token();
    tokenManager.setToken(saved, true);
    getCurrentMember.mockRejectedValueOnce(new ApiRequestError("Unavailable", 503));
    renderSession();
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(tokenManager.getToken()).toBe(saved);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText(member.email)).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([503, "network"] as const)("keeps an expired remembered login during a %s renewal failure", async (failure) => {
    const saved = token(-1);
    tokenManager.setToken(saved, true);
    if (failure === "network") fetchMock.mockRejectedValueOnce(new TypeError("Offline"));
    else fetchMock.mockResolvedValueOnce(new Response("Unavailable", { status: failure }));
    renderSession();
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(tokenManager.getToken()).toBe(saved);
    expect(tokenManager.isRemembered()).toBe(true);
    const renewed = token(3600, "recovered");
    fetchMock.mockResolvedValueOnce(response(renewed));
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText(member.email)).toBeTruthy();
    expect(tokenManager.getToken()).toBe(renewed);
  });

  it("discards a definitively revoked remembered session", async () => {
    tokenManager.setToken(token(-1), true);
    fetchMock.mockResolvedValueOnce(new Response("Revoked", { status: 401 }));
    render(<AuthProvider><Consumer /></AuthProvider>);
    await waitFor(() => expect(tokenManager.getToken()).toBeNull());
    expect(tokenManager.isRemembered()).toBe(false);
    expect(screen.getByText("signed out")).toBeTruthy();
  });

  it("does not renew unchecked sessions after expiry", async () => {
    tokenManager.setToken(token(-1), false);
    render(<AuthProvider><Consumer /></AuthProvider>);
    await waitFor(() => expect(tokenManager.getToken()).toBeNull());
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("renews an open remembered session before expiry", async () => {
    vi.useFakeTimers();
    const renewed = token(3600, "timer-renewed");
    tokenManager.setToken(token(600), true);
    fetchMock.mockResolvedValueOnce(response(renewed));
    await act(async () => { renderSession(); });
    expect(screen.getByText(member.email)).toBeTruthy();
    await act(async () => { await vi.advanceTimersByTimeAsync(571_000); });
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(tokenManager.getToken()).toBe(renewed);
    expect(screen.getByText(member.email)).toBeTruthy();
  });

  it("observes logout in another tab", async () => {
    tokenManager.setToken(token(), true);
    render(<AuthProvider><Consumer /></AuthProvider>);
    await screen.findByText(member.email);
    act(() => {
      localStorage.clear();
      window.dispatchEvent(new StorageEvent("storage", { key: null }));
    });
    expect(screen.getByText("signed out")).toBeTruthy();
  });

  it("waits for renewal when returning to a tab after its access token expired", async () => {
    vi.useFakeTimers();
    const now = Date.now();
    tokenManager.setToken(token(600), true);
    const view = renderSession();
    await act(async () => {});
    let complete!: (result: Response) => void;
    fetchMock.mockReturnValueOnce(new Promise(resolve => { complete = resolve; }));
    vi.setSystemTime(now + 601_000);
    act(() => { view.rerender(<AuthProvider><MemoryRouter><ProtectedRoute><Consumer /></ProtectedRoute></MemoryRouter></AuthProvider>); });
    expect(screen.getByText("Authentication is loading...")).toBeTruthy();
    act(() => { window.dispatchEvent(new Event("focus")); });
    await act(async () => { complete(response(token(3600, "resumed"))); });
    expect(screen.getByText(member.email)).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});

describe("authenticated API renewal", () => {
  it("shares renewal across concurrent requests and attaches the new token", async () => {
    const renewed = token(3600, "concurrent");
    tokenManager.setToken(token(-1), true);
    let complete!: (result: Response) => void;
    fetchMock.mockReturnValueOnce(new Promise(resolve => { complete = resolve; }));
    apiClient.defaults.adapter = async config => {
      expect(config.headers.Authorization).toBe(`Bearer ${renewed}`);
      return { data: {}, status: 200, statusText: "OK", config, headers: {} };
    };
    const requests = Promise.all([apiClient.get("/one"), apiClient.get("/two"), apiClient.get("/three")]);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    complete(response(renewed));
    await requests;
    expect(tokenManager.getToken()).toBe(renewed);
  });

  it("renews once and retries a server-rejected access token", async () => {
    const renewed = token(3600, "retry");
    tokenManager.setToken(token(), true);
    fetchMock.mockResolvedValueOnce(response(renewed));
    let calls = 0;
    apiClient.defaults.adapter = async config => {
      calls++;
      if (calls === 1) throw new AxiosError("Expired", "401", config, undefined, { status: 401, statusText: "Unauthorized", headers: {}, config, data: {} });
      expect(config.headers.Authorization).toBe(`Bearer ${renewed}`);
      return { data: { recovered: true }, status: 200, statusText: "OK", headers: {}, config };
    };
    expect((await apiClient.get("/protected")).data).toEqual({ recovered: true });
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(calls).toBe(2);
  });

  it("does not loop if the server rejects the renewed access token", async () => {
    tokenManager.setToken(token(), true);
    fetchMock.mockResolvedValueOnce(response(token(3600, "rejected")));
    let calls = 0;
    apiClient.defaults.adapter = async config => {
      calls++;
      throw new AxiosError("Revoked", "401", config, undefined, { status: 401, statusText: "Unauthorized", headers: {}, config, data: {} });
    };
    await expect(apiUtils.get("/protected", { redirectOnUnauthorized: false })).rejects.toMatchObject({ status: 401 });
    expect(calls).toBe(2);
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(tokenManager.getToken()).toBeNull();
  });

  it("preserves the saved login when API-triggered renewal is temporarily unavailable", async () => {
    const saved = token(-1);
    tokenManager.setToken(saved, true);
    fetchMock.mockResolvedValueOnce(new Response("Unavailable", { status: 503 }));
    await expect(apiClient.get("/protected")).rejects.toMatchObject({ status: 503 });
    expect(tokenManager.getToken()).toBe(saved);
  });

  it("keeps a new login when an older retried request later returns unauthorized", async () => {
    tokenManager.setToken(token(), true);
    fetchMock.mockResolvedValueOnce(response(token(3600, "renewed-old-session")));
    let complete!: () => void;
    let calls = 0;
    apiClient.defaults.adapter = async config => {
      calls++;
      if (calls === 2) await new Promise<void>(resolve => { complete = resolve; });
      throw new AxiosError("Unauthorized", "401", config, undefined, { status: 401, statusText: "Unauthorized", headers: {}, config, data: {} });
    };
    const rejected = expect(apiUtils.get("/protected", { redirectOnUnauthorized: false })).rejects.toMatchObject({ status: 401 });
    await waitFor(() => expect(calls).toBe(2));
    const newLogin = token(3600, "new-login");
    tokenManager.setToken(newLogin, true);
    complete();
    await rejected;
    expect(tokenManager.getToken()).toBe(newLogin);
  });

  it("does not restore a session from a late renewal after logout", async () => {
    tokenManager.setToken(token(-1), true);
    let complete!: (result: Response) => void;
    fetchMock.mockReturnValueOnce(new Promise(resolve => { complete = resolve; }));
    const pending = refreshSession();
    fetchMock.mockResolvedValueOnce(new Response("", { status: 200 }));
    await endSession();
    complete(response(token(3600, "late")));
    expect(await pending).toBeNull();
    expect(tokenManager.getToken()).toBeNull();
    expect(tokenManager.isRemembered()).toBe(false);
  });

  it("waits for cookie deletion before a subsequent login", async () => {
    let complete!: (result: Response) => void;
    fetchMock.mockReturnValueOnce(new Promise(resolve => { complete = resolve; }));
    const logout = endSession();
    const ready = vi.fn();
    const nextLogin = waitForLogout().then(ready);
    await Promise.resolve();
    expect(ready).not.toHaveBeenCalled();
    complete(new Response("", { status: 200 }));
    await Promise.all([logout, nextLogin]);
    expect(ready).toHaveBeenCalledOnce();
  });
});
