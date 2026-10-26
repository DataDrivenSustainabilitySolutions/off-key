import { Suspense } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider, type RouteObject } from "react-router-dom";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const { captureRouter, auth } = vi.hoisted(() => ({
  captureRouter: vi.fn<(routes: RouteObject[]) => unknown>(),
  auth: { isAuthenticated: true, isLoading: false, guestChecked: true },
}));
vi.mock("react-router-dom", async (original) => ({
  ...(await original<typeof import("react-router-dom")>()),
  createBrowserRouter: captureRouter,
}));
vi.mock("@/auth/AuthContext", () => ({ useAuth: () => auth }));
vi.mock("@/pages/MonitoringWorkspace", () => ({ default: () => <h1>Monitoring home</h1> }));
vi.mock("@/pages/Login", () => ({ default: () => <h1>Sign in</h1> }));
vi.mock("@/pages/SystemCatalogue", () => ({ default: () => <h1>Sources</h1> }));
vi.mock("@/pages/Anomalies", () => ({ default: () => <h1>Reporting</h1> }));
vi.mock("@/pages/Account", () => ({ default: () => <h1>Account</h1> }));
vi.mock("@/pages/SystemStatus", () => ({ default: () => <h1>System status</h1> }));
vi.mock("@/components/theme-provider", () => ({ useTheme: () => ({ resolvedTheme: "light", setTheme: vi.fn() }) }));
vi.mock("@/lib/api-client", async original => {
  const actual = await original<typeof import("@/lib/api-client")>();
  const { createEmptySystem } = await import("@/domain/system/systemDocument");
  return { ...actual, apiUtils: { ...actual.apiUtils, get: vi.fn(async () => ({
    document: createEmptySystem(), revision: 0, can_edit: false, storage_origin: "saved", runtime: { mode: "configured_only", message: "" },
  })) } };
});

let routes: RouteObject[];
beforeAll(async () => {
  await import("@/app/App");
  await import("@/app/ApplicationWorkspace");
  routes = captureRouter.mock.calls[0]![0];
});
beforeEach(() => {
  auth.isAuthenticated = true; auth.isLoading = false;
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
});

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

  it("keeps old entity-directory links usable by taking them to Sources", async () => {
    const router = visit("/entities");
    expect(await screen.findByRole("heading", { name: "Sources" })).toBeTruthy();
    expect(router.state.location.pathname).toBe("/sources");
  });

  it.each(["/system/status", "/account/settings"])("opens diagnostics from %s", async (path) => {
    const router = visit(path);
    expect(await screen.findByRole("heading", { name: "System status" })).toBeTruthy();
    expect(router.state.location.pathname).toBe("/system/status");
    fireEvent.keyDown(screen.getByRole("button", { name: "Application menu" }), { key: "Enter" });
    expect(screen.getByRole("menuitem", { name: "System status" }).getAttribute("aria-current")).toBe("page");
  });

  it("keeps the primary navigation on Reporting and provides a way back to Monitoring", async () => {
    const router = visit("/anomalies");
    await screen.findByRole("heading", { name: "Reporting" });
    const workspaces = within(screen.getByRole("group", { name: "Workspaces" }));
    expect(workspaces.getAllByRole("link").map(link => link.textContent)).toEqual(["Monitoring", "Sources", "Reporting"]);
    expect(workspaces.getByRole("link", { name: "Reporting" }).getAttribute("aria-current")).toBe("page");
    fireEvent.click(workspaces.getByRole("link", { name: "Monitoring" }));
    await screen.findByRole("heading", { name: "Monitoring home" });
    expect(router.state.location.pathname).toBe("/");
  });

  it("keeps navbar navigation visible when the catalogue is hidden", async () => {
    visit("/anomalies");
    await screen.findByRole("heading", { name: "Reporting" });
    fireEvent.click(screen.getByRole("button", { name: "Hide catalogue" }));
    expect(screen.queryByRole("navigation", { name: "System explorer" })).toBeNull();
    expect(screen.getByRole("group", { name: "Workspaces" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Show catalogue" }));
    expect(screen.getByRole("navigation", { name: "System explorer" })).toBeTruthy();
  });

  it("keeps mobile section navigation in the navbar and uses the drawer for MQTT entities", async () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    const router = visit("/account");
    await screen.findByRole("heading", { name: "Account" });
    const trigger = screen.getByRole("button", { name: "Show catalogue" });
    fireEvent.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "MQTT catalogue" });
    expect(within(dialog).queryByRole("link", { name: "Reporting" })).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Hide catalogue" }));
    await waitFor(() => expect(document.activeElement).toBe(trigger));
    fireEvent.click(screen.getByRole("link", { name: "Reporting" }));
    await screen.findByRole("heading", { name: "Reporting" });
    expect(router.state.location.pathname).toBe("/anomalies");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("preserves the selected catalogue entity when opening the monitoring workspace", async () => {
    const router = visit("/?entity=entity%3Awarehouse%2Fgateway");
    expect(await screen.findByRole("heading", { name: "Monitoring home" })).toBeTruthy();
    expect(new URLSearchParams(router.state.location.search).get("entity")).toBe("entity:warehouse/gateway");
  });
});
