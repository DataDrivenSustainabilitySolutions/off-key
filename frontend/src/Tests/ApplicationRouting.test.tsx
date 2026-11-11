import { Suspense } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider, type RouteObject } from "react-router-dom";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { loadExplorerPreferences } from "@/features/workspace/preferences";

const { captureRouter, auth } = vi.hoisted(() => ({
  captureRouter: vi.fn<(routes: RouteObject[]) => unknown>(),
  auth: { isAuthenticated: true, isLoading: false, can: () => false },
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
  localStorage.clear();
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

  it.each([["/system/status", "status", "System status"], ["/account/settings", "status", "System status"], ["/account", "account", "Account"]])(
    "opens %s as a settings section above Monitoring", async (path, section, heading) => {
      const router = visit(path);
      const dialog = await screen.findByRole("dialog", { name: "Settings" });
      expect(await within(dialog).findByRole("heading", { name: heading, level: 2 })).toBeTruthy();
      expect(screen.getByRole("heading", { name: "Monitoring home", hidden: true })).toBeTruthy();
      expect(router.state.location.pathname).toBe("/");
      expect(router.state.location.search).toBe(`?settings=${section}`);
      fireEvent.click(within(dialog).getByRole("button", { name: "Close settings" }));
      await waitFor(() => expect(router.state.location.search).toBe(""));
      expect(router.state.location.pathname).toBe("/");
    });

  it("opens catalogue settings from an earlier link as the overlay's catalogue section", async () => {
    const router = visit("/sources?catalogue=settings");
    const dialog = await screen.findByRole("dialog", { name: "Settings" });
    expect(await within(dialog).findByRole("heading", { name: "Catalogue", level: 2 })).toBeTruthy();
    await waitFor(() => expect(router.state.location.search).toBe("?settings=catalogue"));
    expect(router.state.location.pathname).toBe("/sources");
  });

  it("lists the workspaces in the sidebar instead of a top navigation bar and marks the current one", async () => {
    const router = visit("/anomalies");
    await screen.findByRole("heading", { name: "Reporting" });
    expect(screen.queryByRole("navigation", { name: "Primary navigation" })).toBeNull();
    expect(screen.queryByTestId("application-header")).toBeNull();
    const sidebar = within(screen.getByRole("complementary", { name: "Sidebar" }));
    const workspaces = within(sidebar.getByRole("navigation", { name: "Workspace" }));
    // Dojo stays hidden from a member without the Dojo permission.
    expect(workspaces.getAllByRole("link").map(link => link.textContent)).toEqual(["Monitoring", "Sources", "Reporting"]);
    expect(workspaces.getByRole("link", { name: "Reporting" }).getAttribute("aria-current")).toBe("page");
    expect(sidebar.getByRole("navigation", { name: "Catalogue" })).toBeTruthy();
    expect(sidebar.getByRole("button", { name: "Account menu" })).toBeTruthy();
    fireEvent.click(workspaces.getByRole("link", { name: "Monitoring" }));
    await screen.findByRole("heading", { name: "Monitoring home" });
    expect(router.state.location.pathname).toBe("/");
    expect(workspaces.getByRole("link", { name: "Monitoring" }).getAttribute("aria-current")).toBe("page");
    expect(workspaces.getByRole("link", { name: "Reporting" }).getAttribute("aria-current")).toBeNull();
  });

  it("leaves an obvious way back when the sidebar is hidden and remembers the choice", async () => {
    visit("/anomalies");
    await screen.findByRole("heading", { name: "Reporting" });
    const sidebar = screen.getByRole("complementary", { name: "Sidebar" });
    fireEvent.click(within(sidebar).getByRole("button", { name: "Hide sidebar" }));
    expect(sidebar.hasAttribute("inert")).toBe(true);
    const show = await screen.findByRole("button", { name: "Show sidebar" });
    await waitFor(() => expect(document.activeElement).toBe(show));
    await waitFor(() => expect(loadExplorerPreferences(null).sidebarOpen).toBe(false));
    fireEvent.click(show);
    expect(sidebar.hasAttribute("inert")).toBe(false);
    await waitFor(() => expect(document.activeElement).toBe(within(sidebar).getByRole("button", { name: "Hide sidebar" })));
    expect(screen.queryByRole("button", { name: "Show sidebar" })).toBeNull();
    await waitFor(() => expect(loadExplorerPreferences(null).sidebarOpen).toBe(true));
  });

  it("opens settings from the sidebar account menu above the current page without remounting it", async () => {
    const router = visit("/anomalies?source=kept");
    const page = await screen.findByRole("heading", { name: "Reporting" });
    const account = within(screen.getByRole("complementary", { name: "Sidebar" })).getByRole("button", { name: "Account menu" });
    fireEvent.keyDown(account, { key: "Enter" });
    fireEvent.click(screen.getByRole("menuitem", { name: "Preferences" }));
    const dialog = await screen.findByRole("dialog", { name: "Settings" });
    expect(await within(dialog).findByRole("heading", { name: "Appearance", level: 2 })).toBeTruthy();
    expect(router.state.location.pathname).toBe("/anomalies");
    expect(new URLSearchParams(router.state.location.search).get("source")).toBe("kept");
    expect(new URLSearchParams(router.state.location.search).get("settings")).toBe("preferences");
    fireEvent.click(within(dialog).getByRole("button", { name: "Close settings" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Settings" })).toBeNull());
    expect(screen.getByRole("heading", { name: "Reporting" })).toBe(page);
    expect(router.state.location.search).toBe("?source=kept");
    await waitFor(() => expect(document.activeElement).toBe(account));
  });

  it("uses one focus-trapped drawer on phones, closes it on navigation and returns focus to its trigger", async () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    const router = visit("/sources");
    await screen.findByRole("heading", { name: "Sources" });
    expect(screen.queryByRole("complementary", { name: "Sidebar" })).toBeNull();
    const trigger = screen.getByRole("button", { name: "Show sidebar" });
    fireEvent.click(trigger);
    let drawer = await screen.findByRole("dialog", { name: "Navigation" });
    expect(within(drawer).getByRole("navigation", { name: "Catalogue" })).toBeTruthy();
    fireEvent.keyDown(drawer, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Navigation" })).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(trigger));
    fireEvent.click(trigger);
    drawer = await screen.findByRole("dialog", { name: "Navigation" });
    fireEvent.click(within(drawer).getByRole("link", { name: "Reporting" }));
    await screen.findByRole("heading", { name: "Reporting" });
    expect(router.state.location.pathname).toBe("/anomalies");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("preserves the selected catalogue entity when opening the monitoring workspace", async () => {
    const router = visit("/?entity=entity%3Awarehouse%2Fgateway");
    expect(await screen.findByRole("heading", { name: "Monitoring home" })).toBeTruthy();
    expect(new URLSearchParams(router.state.location.search).get("entity")).toBe("entity:warehouse/gateway");
  });
});
