import { Suspense } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider, type RouteObject } from "react-router-dom";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const { captureRouter, auth } = vi.hoisted(() => ({
  captureRouter: vi.fn<(routes: RouteObject[]) => unknown>(),
  auth: { isAuthenticated: true, isLoading: false },
}));
vi.mock("react-router-dom", async (original) => ({
  ...(await original<typeof import("react-router-dom")>()),
  createBrowserRouter: captureRouter,
}));
vi.mock("@/auth/AuthContext", () => ({ useAuth: () => auth }));
vi.mock("@/pages/MonitoringWorkspace", () => ({ default: () => <h1>Monitoring home</h1> }));
vi.mock("@/pages/Login", () => ({ default: () => <h1>Sign in</h1> }));
vi.mock("@/pages/SystemCatalogue", () => ({ default: () => <h1>Data sources</h1> }));
vi.mock("@/pages/Anomalies", () => ({ default: () => <h1>Anomalies</h1> }));
vi.mock("@/pages/Account", () => ({ default: () => <h1>Account</h1> }));
vi.mock("@/pages/SystemStatus", () => ({ default: () => <h1>System status</h1> }));
vi.mock("@/components/theme-provider", () => ({ useTheme: () => ({ resolvedTheme: "light", setTheme: vi.fn() }) }));

let routes: RouteObject[];
beforeAll(async () => {
  await import("@/App");
  routes = captureRouter.mock.calls[0]![0];
});
beforeEach(() => {
  auth.isAuthenticated = true; auth.isLoading = false;
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function visit(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<Suspense fallback={<p>Loading</p>}><RouterProvider router={router} /></Suspense>);
  return router;
}

describe("application home", () => {
  it.each(["/", "/services"])("opens the monitoring home from %s for signed-in users", async (path) => {
    const router = visit(path);
    expect(await screen.findByRole("heading", { name: "Monitoring home" })).toBeTruthy();
    expect(router.state.location.pathname).toBe("/");
  });

  it.each(["/", "/entities", "/anomalies", "/system/status", "/account/settings"])("requires sign-in from %s", async (path) => {
    auth.isAuthenticated = false;
    const router = visit(path);
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeTruthy();
    expect(router.state.location.pathname).toBe("/login");
    expect(screen.queryByRole("heading", { name: "Monitoring home" })).toBeNull();
  });

  it("waits for account verification before mounting the workspace", () => {
    auth.isLoading = true;
    visit("/");
    expect(screen.getByText("Authentication is loading...")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Monitoring home" })).toBeNull();
  });

  it("keeps old entity-directory links usable by taking them to Data sources", async () => {
    const router = visit("/entities");
    expect(await screen.findByRole("heading", { name: "Data sources" })).toBeTruthy();
    expect(router.state.location.pathname).toBe("/sources");
  });

  it.each(["/system/status", "/account/settings"])("opens diagnostics from %s", async (path) => {
    const router = visit(path);
    expect(await screen.findByRole("heading", { name: "System status" })).toBeTruthy();
    expect(router.state.location.pathname).toBe("/system/status");
    fireEvent.keyDown(screen.getByRole("button", { name: "Application menu" }), { key: "Enter" });
    expect(screen.getByRole("menuitem", { name: "System status" }).getAttribute("aria-current")).toBe("page");
  });

  it("keeps the primary navigation on Anomalies and provides a way back to Monitoring", async () => {
    const router = visit("/anomalies");
    await screen.findByRole("heading", { name: "Anomalies" });
    const workspaces = within(screen.getByRole("group", { name: "Workspaces" }));
    expect(workspaces.getAllByRole("link").map(link => link.textContent)).toEqual(["Monitoring", "Data sources", "Anomalies"]);
    expect(workspaces.getByRole("link", { name: "Anomalies" }).getAttribute("aria-current")).toBe("page");
    fireEvent.click(workspaces.getByRole("link", { name: "Monitoring" }));
    await screen.findByRole("heading", { name: "Monitoring home" });
    expect(router.state.location.pathname).toBe("/");
  });

  it("can reopen the desktop navigation after hiding it", async () => {
    visit("/anomalies");
    await screen.findByRole("heading", { name: "Anomalies" });
    fireEvent.click(screen.getByRole("button", { name: "Toggle workspace navigation" }));
    expect(screen.queryByRole("group", { name: "Workspaces" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Toggle workspace navigation" }));
    expect(screen.getByRole("group", { name: "Workspaces" })).toBeTruthy();
  });

  it("closes the mobile navigation after choosing a page and restores toggle focus", async () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    const router = visit("/account");
    await screen.findByRole("heading", { name: "Account" });
    fireEvent.click(screen.getByRole("button", { name: "Toggle workspace navigation" }));
    const dialog = await screen.findByRole("dialog", { name: "Workspace navigation" });
    fireEvent.click(within(dialog).getByRole("link", { name: "Anomalies" }));
    await screen.findByRole("heading", { name: "Anomalies" });
    expect(router.state.location.pathname).toBe("/anomalies");
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Toggle workspace navigation" })));
  });

  it("preserves the selected catalogue entity when opening the monitoring workspace", async () => {
    const router = visit("/?entity=entity%3Awarehouse%2Fgateway");
    expect(await screen.findByRole("heading", { name: "Monitoring home" })).toBeTruthy();
    expect(new URLSearchParams(router.state.location.search).get("entity")).toBe("entity:warehouse/gateway");
  });
});
