import { Suspense } from "react";
import { cleanup, render, screen } from "@testing-library/react";
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
vi.mock("@/pages/Entities", () => ({ default: () => <h1>Entity directory</h1> }));

let routes: RouteObject[];
beforeAll(async () => {
  await import("@/App");
  routes = captureRouter.mock.calls[0]![0];
});
beforeEach(() => { auth.isAuthenticated = true; auth.isLoading = false; });
afterEach(cleanup);

function visit(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<Suspense fallback={<p>Loading</p>}><RouterProvider router={router} /></Suspense>);
  return router;
}

describe("application home", () => {
  it.each(["/", "/explorer", "/spatial-lab", "/services"])("opens the monitoring home from %s for signed-in users", async (path) => {
    const router = visit(path);
    expect(await screen.findByRole("heading", { name: "Monitoring home" })).toBeTruthy();
    expect(router.state.location.pathname).toBe("/");
  });

  it.each(["/", "/explorer", "/spatial-lab", "/entities", "/stations", "/favourites"])("requires sign-in from %s", async (path) => {
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

  it.each(["/entities", "/stations", "/stations?state=online", "/favourites"])("opens the generic entity directory from %s", async (path) => {
    const router = visit(path);
    expect(await screen.findByRole("heading", { name: "Entity directory" })).toBeTruthy();
    expect(router.state.location.pathname).toBe("/entities");
  });

  it("preserves the selected catalogue entity when opening the monitoring workspace", async () => {
    const router = visit("/?entity=entity%3Awarehouse%2Fgateway");
    expect(await screen.findByRole("heading", { name: "Monitoring home" })).toBeTruthy();
    expect(new URLSearchParams(router.state.location.search).get("entity")).toBe("entity:warehouse/gateway");
  });
});
