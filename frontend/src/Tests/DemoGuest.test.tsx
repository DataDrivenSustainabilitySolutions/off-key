import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "@/auth/AuthContext";
import { isDemoGuest } from "@/auth/demo";
import { ProtectedRoute } from "@/auth/ProtectedRoute";
import { tokenManager } from "@/auth/session";

const { getCurrentMember } = vi.hoisted(() => ({ getCurrentMember: vi.fn() }));
vi.mock("@/lib/member-api", () => ({ getCurrentMember }));

const viewer = { id: 5, email: "viewer@example.com", role: "user", is_active: true, is_verified: true };
const fetchMock = vi.fn<typeof fetch>();
const demo = (enabled: boolean) => new Response(JSON.stringify({ enabled }), { status: 200 });

beforeEach(() => {
  tokenManager.removeToken();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  getCurrentMember.mockReset().mockResolvedValue(viewer);
});

afterEach(() => tokenManager.removeToken());

const Workspace = () => {
  const { isGuest, isAdmin, member } = useAuth();
  return <p>{isGuest ? "guest" : "member"} {isAdmin ? "admin" : "reader"} {member?.email}</p>;
};
const visit = () => render(<AuthProvider><MemoryRouter><Routes>
  <Route path="/" element={<ProtectedRoute><Workspace /></ProtectedRoute>} />
  <Route path="/login" element={<h1>Sign in</h1>} />
</Routes></MemoryRouter></AuthProvider>);

describe("public demo guests", () => {
  it("lets signed-out visitors of a demo browse read-only as the viewer", async () => {
    fetchMock.mockResolvedValueOnce(demo(true));
    visit();
    expect(await screen.findByText("guest reader viewer@example.com")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/demo", expect.anything());
    expect(isDemoGuest()).toBe(true);
    expect(tokenManager.getToken()).toBeNull();
  });

  it("sends signed-out visitors to sign in when the installation is no demo", async () => {
    fetchMock.mockResolvedValueOnce(demo(false));
    visit();
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeTruthy();
    expect(getCurrentMember).not.toHaveBeenCalled();
  });

  it("falls back to sign in when the demo status cannot be read", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("offline"));
    visit();
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeTruthy();
  });

  it("reports an unavailable demo instead of redirecting", async () => {
    fetchMock.mockResolvedValueOnce(demo(true));
    getCurrentMember.mockRejectedValueOnce(new Error("503"));
    visit();
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText(/public demo is unavailable/)).toBeTruthy();
  });

  it("does not ask while a member is signed in", async () => {
    tokenManager.setToken(`header.${btoa(JSON.stringify({ user_id: 5, exp: Math.floor(Date.now() / 1000) + 3600 }))}.signature`);
    visit();
    await waitFor(() => expect(screen.getByText("member reader viewer@example.com")).toBeTruthy());
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
