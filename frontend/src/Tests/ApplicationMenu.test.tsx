import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApplicationMenu } from "@/components/ApplicationMenu";
import { BrandHome } from "@/components/BrandHome";
import { ThemeProvider } from "@/components/theme-provider";

const auth = vi.hoisted(() => ({ isAuthenticated: true, member: null as { email: string } | null, logout: vi.fn() }));
vi.mock("@/auth/AuthContext", () => ({ useAuth: () => auth }));
beforeEach(() => localStorage.clear());
afterEach(() => { cleanup(); auth.isAuthenticated = true; auth.member = null; vi.clearAllMocks(); document.documentElement.className = ""; });

function Location() {
  const location = useLocation();
  return <p>{location.pathname + location.search}</p>;
}
function mount(path = "/") {
  render(<ThemeProvider defaultTheme="light"><MemoryRouter initialEntries={[path]}><BrandHome /><ApplicationMenu /><Location /></MemoryRouter></ThemeProvider>);
  fireEvent.keyDown(screen.getByRole("button", { name: "Application menu" }), { key: "Enter" });
}

describe("shared application menu", () => {
  it("logs out and returns to sign-in immediately", async () => {
    mount();
    fireEvent.click(screen.getByRole("menuitem", { name: "Log out" }));
    expect(auth.logout).toHaveBeenCalledOnce();
    expect(await screen.findByText("/login")).toBeTruthy();
  });

  it.each(["/", "/sources", "/anomalies", "/details/entity-one"])("offers shared preferences and system status at %s", (path) => {
    mount(path);
    expect(screen.getAllByRole("menuitem").map(item => item.textContent)).toEqual(["Account", "Preferences", "System status", "Log out"]);
  });

  it("shows who is signed in on the menu trigger", () => {
    auth.member = { email: "jane.doe@example.com" };
    mount();
    const trigger = screen.getByRole("button", { name: "Application menu", hidden: true });
    expect(trigger.textContent).toBe("JD");
    expect(trigger.getAttribute("title")).toBe("jane.doe@example.com");
    expect(screen.getByText("jane.doe@example.com", { selector: ".app-menu-account" })).toBeTruthy();
  });

  it.each([["/account", "Account"], ["/system/status", "System status"]])("marks the current page at %s", (path, label) => {
    mount(path);
    expect(screen.getByRole("menuitem", { name: label }).getAttribute("aria-current")).toBe("page");
  });

  it("offers sign-in without authenticated application actions", () => {
    auth.isAuthenticated = false;
    render(<MemoryRouter><ApplicationMenu /></MemoryRouter>);
    expect(screen.getByRole("link", { name: "Log in" }).getAttribute("href")).toBe("/login");
    expect(screen.queryByRole("button", { name: "Application menu" })).toBeNull();
  });

  it("links directly to system diagnostics", async () => {
    mount();
    fireEvent.click(screen.getByRole("menuitem", { name: "System status" }));
    expect(await screen.findByText("/system/status")).toBeTruthy();
  });

  it("opens preferences over the current route, persists the theme and restores menu focus", async () => {
    const path = "/sources?reading=temperature";
    mount(path);
    fireEvent.click(screen.getByRole("menuitem", { name: "Preferences" }));
    const dialog = await screen.findByRole("dialog", { name: "Preferences" });
    expect(screen.getByText(path)).toBeTruthy();
    expect(within(dialog).getByRole("tab", { name: "Appearance" }).getAttribute("aria-selected")).toBe("true");
    expect(within(dialog).queryByText("Collection diagnostics")).toBeNull();
    expect((within(dialog).getByRole("radio", { name: "Light" }) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(within(dialog).getByRole("radio", { name: "Dark" }));
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(localStorage.getItem("vite-ui-theme")).toBe("dark");
    expect((within(dialog).getByRole("radio", { name: "Dark" }) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(within(dialog).getByRole("button", { name: "Close preferences" }));
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Application menu" })));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByText(path)).toBeTruthy();
  });

  it("preserves a newer focus choice while preferences finishes closing", async () => {
    mount("/sources");
    fireEvent.click(screen.getByRole("menuitem", { name: "Preferences" }));
    const dialog = await screen.findByRole("dialog", { name: "Preferences" });
    vi.useFakeTimers();
    try {
      fireEvent.click(within(dialog).getByRole("button", { name: "Close preferences" }));
      const home = screen.getByRole("link", { name: "Aberration home" });
      home.focus();
      expect(document.activeElement).toBe(home);
      await act(async () => { await vi.runOnlyPendingTimersAsync(); });
      expect(document.activeElement).toBe(home);
    } finally {
      vi.useRealTimers();
    }
  });

  it("closes preferences with Escape and reopens the saved choice", async () => {
    mount();
    fireEvent.click(screen.getByRole("menuitem", { name: "Preferences" }));
    const dialog = await screen.findByRole("dialog", { name: "Preferences" });
    fireEvent.click(within(dialog).getByRole("radio", { name: "Follow system" }));
    expect(localStorage.getItem("vite-ui-theme")).toBe("system");
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Application menu" })));
    fireEvent.keyDown(screen.getByRole("button", { name: "Application menu" }), { key: "Enter" });
    fireEvent.click(screen.getByRole("menuitem", { name: "Preferences" }));
    const reopened = await screen.findByRole("dialog", { name: "Preferences" });
    expect((within(reopened).getByRole("radio", { name: "Follow system" }) as HTMLInputElement).checked).toBe(true);
  });
});
