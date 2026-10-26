import { Suspense } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { createAppRoutes } from "../app/routes";

const auth = vi.hoisted(() => ({ isAuthenticated: false, isLoading: false, guestChecked: true }));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => auth }));
vi.mock("../pages/Login", () => ({ default: () => <h1>Log in</h1> }));
vi.mock("../pages/MonitoringWorkspace", () => ({ default: () => <h1>Monitoring workspace</h1> }));
vi.mock("../pages/Account", () => ({
  default: () => { throw new Error("Internal rendering details"); },
}));

let router: ReturnType<typeof createMemoryRouter>;

function renderRoute(path: string, routes = createAppRoutes()) {
  router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <Suspense fallback={<p>Loading page...</p>}>
      <RouterProvider router={router} />
    </Suspense>,
  );
}

beforeAll(async () => {
  await import("@/app/ApplicationWorkspace");
});

beforeEach(() => {
  auth.isAuthenticated = false;
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
});

afterEach(() => {
  router.dispose();
});

describe("application route recovery", () => {
  it.each([false, true])("shows a missing page and recovers home (signed in: %s)", async (signedIn) => {
    auth.isAuthenticated = signedIn;
    renderRoute("/does-not-exist/nested?source=bookmark");

    expect(screen.getByRole("heading", { name: "Page not found", level: 1 })).toBeTruthy();
    expect(screen.queryByText(/Hey developer/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Reload page" })).toBeNull();
    fireEvent.click(screen.getByRole("link", { name: "Go home" }));

    expect(await screen.findByRole("heading", {
      name: signedIn ? "Monitoring workspace" : "Log in",
    })).toBeTruthy();
    expect(router.state.location.pathname).toBe(signedIn ? "/" : "/login");
  });

  it.each(["/account/does-not-exist", "/details", "/monitoring"])("handles an unknown nested or incomplete URL: %s", (path) => {
    renderRoute(path);
    expect(screen.getByRole("heading", { name: "Page not found" })).toBeTruthy();
    expect(router.state.location.pathname).toBe(path);
  });

  it("continues to protect existing account routes", async () => {
    renderRoute("/account/settings");
    expect(await screen.findByRole("heading", { name: "Log in" })).toBeTruthy();
    expect(router.state.location.pathname).toBe("/login");
  });

  it("catches rendering failures without exposing details and recovers home", async () => {
    auth.isAuthenticated = true;
    vi.spyOn(console, "error").mockImplementation(() => {});
    renderRoute("/account");

    expect(await screen.findByRole("heading", { name: "Something went wrong" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reload page" })).toBeTruthy();
    expect(screen.queryByText(/Internal rendering details|Hey developer/)).toBeNull();
    fireEvent.click(screen.getByRole("link", { name: "Go home" }));
    expect(await screen.findByRole("heading", { name: "Monitoring workspace" })).toBeTruthy();
    expect(router.state.location.pathname).toBe("/");
  });

  it("uses the missing-page screen for a loader's 404 response", async () => {
    const routes = createAppRoutes().map((route) => route.index ? route : ({
      ...route,
      children: [
        ...(route.children ?? []),
        {
          path: "/missing-record",
          loader: () => { throw new Response("Internal response details", { status: 404 }); },
          element: <p>Record</p>,
        },
      ],
    }));
    renderRoute("/missing-record", routes);

    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeTruthy();
    expect(screen.queryByText(/Internal response details|Hey developer/)).toBeNull();
    fireEvent.click(screen.getByRole("link", { name: "Go home" }));
    expect(await screen.findByRole("heading", { name: "Log in" })).toBeTruthy();
  });
});
