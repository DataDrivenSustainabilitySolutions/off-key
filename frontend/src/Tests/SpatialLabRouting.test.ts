import { afterEach, describe, expect, it, vi } from "vitest";
import { matchRoutes, type RouteObject } from "react-router-dom";

const { captureRouter } = vi.hoisted(() => ({
  captureRouter: vi.fn<(routes: RouteObject[]) => unknown>(),
}));

vi.mock("react-router-dom", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-router-dom")>()),
  createBrowserRouter: captureRouter,
}));

describe("monitoring home routing", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it.each([
    { development: true, flag: undefined, enabled: true },
    { development: true, flag: "false", enabled: true },
    { development: false, flag: undefined, enabled: true },
    { development: false, flag: "false", enabled: true },
    { development: false, flag: "", enabled: true },
    { development: false, flag: "1", enabled: true },
    { development: false, flag: "TRUE", enabled: true },
    { development: false, flag: "true", enabled: true },
  ])(
    "DEV=$development and legacy build flag=$flag retains the protected home and legacy redirects",
    async ({ development, flag, enabled }) => {
      vi.resetModules();
      captureRouter.mockClear();
      vi.stubEnv("DEV", development);
      vi.stubEnv("VITE_SPATIAL_LAB_ENABLED", flag);

      await import("@/App");

      const routes = captureRouter.mock.calls[0]![0];
      expect(matchRoutes(routes, "/spatial-lab") !== null).toBe(enabled);
      expect(matchRoutes(routes, "/explorer") !== null).toBe(enabled);
      if (enabled) {
        const matches = matchRoutes(routes, "/spatial-lab")!;
        const redirect = matches[matches.length - 1]!.route.element;
        expect(redirect).toMatchObject({ props: { to: "/", replace: true } });
      }
      const home = matchRoutes(routes, "/")!;
      const explorer = matchRoutes(routes, "/explorer")!;
      expect(home[0]!.route).toBe(explorer[0]!.route);
      expect(home[0]!.route.element).toMatchObject({ props: { children: expect.anything() } });
      expect(explorer[explorer.length - 1]!.route.element).toMatchObject({ props: { to: "/", replace: true } });
      expect(matchRoutes(routes, "/login")).not.toBeNull();
      expect(matchRoutes(routes, "/sources")).not.toBeNull();
      expect(matchRoutes(routes, "/stations")).not.toBeNull();
    },
  );
});
