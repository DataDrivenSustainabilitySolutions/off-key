import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApplicationMenu } from "@/app/ApplicationMenu";
import { SettingsOverlay } from "@/app/SettingsOverlay";
import { BrandHome } from "@/components/BrandHome";
import { ThemeProvider } from "@/components/theme-provider";

const auth = vi.hoisted(() => ({ isAuthenticated: true, member: null as { email: string } | null, logout: vi.fn() }));
vi.mock("@/auth/AuthContext", () => ({ useAuth: () => auth }));
afterEach(() => { auth.isAuthenticated = true; auth.member = null; document.documentElement.className = ""; });

function Location() {
  const location = useLocation();
  return <p>{location.pathname + location.search}</p>;
}
function mount(path = "/") {
  render(<ThemeProvider defaultTheme="light"><MemoryRouter initialEntries={[path]}><BrandHome /><ApplicationMenu /><SettingsOverlay /><Location /></MemoryRouter></ThemeProvider>);
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

  it("offers sign-in without authenticated application actions", () => {
    auth.isAuthenticated = false;
    render(<MemoryRouter><ApplicationMenu /></MemoryRouter>);
    expect(screen.getByRole("link", { name: "Log in" }).getAttribute("href")).toBe("/login");
    expect(screen.queryByRole("button", { name: "Application menu" })).toBeNull();
  });

  it.each([["Account", "account"], ["System status", "status"]])("opens %s as a settings section above the current page", async (label, section) => {
    mount("/sources?reading=temperature");
    fireEvent.click(screen.getByRole("menuitem", { name: label }));
    const dialog = await screen.findByRole("dialog", { name: "Settings" });
    expect(screen.getByText(`/sources?reading=temperature&settings=${section}`)).toBeTruthy();
    expect(within(dialog).getByRole("heading", { name: label, level: 2 })).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: label }).getAttribute("aria-current")).toBe("page");
  });

  it("switches sections in place and closes back to the page it opened from", async () => {
    mount("/anomalies");
    fireEvent.click(screen.getByRole("menuitem", { name: "Account" }));
    const dialog = await screen.findByRole("dialog", { name: "Settings" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Preferences" }));
    expect(await screen.findByText("/anomalies?settings=preferences")).toBeTruthy();
    expect(within(dialog).getByRole("heading", { name: "Preferences", level: 2 })).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Close settings" }));
    expect(await screen.findByText("/anomalies")).toBeTruthy();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("opens a linked section directly and closes it without leaving the page", async () => {
    render(<ThemeProvider defaultTheme="light"><MemoryRouter initialEntries={["/sources?settings=preferences"]}><SettingsOverlay /><Location /></MemoryRouter></ThemeProvider>);
    const dialog = await screen.findByRole("dialog", { name: "Settings" });
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(await screen.findByText("/sources")).toBeTruthy();
  });

  it("opens preferences over the current route, persists the theme and restores menu focus", async () => {
    const path = "/sources?reading=temperature";
    mount(path);
    fireEvent.click(screen.getByRole("menuitem", { name: "Preferences" }));
    const dialog = await screen.findByRole("dialog", { name: "Settings" });
    expect(screen.getByText(`${path}&settings=preferences`)).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Preferences" }).getAttribute("aria-current")).toBe("page");
    expect(within(dialog).queryByText("Collection diagnostics")).toBeNull();
    expect((within(dialog).getByRole("radio", { name: "Light" }) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(within(dialog).getByRole("radio", { name: "Dark" }));
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(localStorage.getItem("vite-ui-theme")).toBe("dark");
    expect((within(dialog).getByRole("radio", { name: "Dark" }) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(within(dialog).getByRole("button", { name: "Close settings" }));
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Application menu" })));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(await screen.findByText(path)).toBeTruthy();
  });

  it("preserves a newer focus choice while preferences finishes closing", async () => {
    mount("/sources");
    fireEvent.click(screen.getByRole("menuitem", { name: "Preferences" }));
    const dialog = await screen.findByRole("dialog", { name: "Settings" });
    vi.useFakeTimers();
    try {
      fireEvent.click(within(dialog).getByRole("button", { name: "Close settings" }));
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
    const dialog = await screen.findByRole("dialog", { name: "Settings" });
    fireEvent.click(within(dialog).getByRole("radio", { name: "Follow system" }));
    expect(localStorage.getItem("vite-ui-theme")).toBe("system");
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Application menu" })));
    fireEvent.keyDown(screen.getByRole("button", { name: "Application menu" }), { key: "Enter" });
    fireEvent.click(screen.getByRole("menuitem", { name: "Preferences" }));
    const reopened = await screen.findByRole("dialog", { name: "Settings" });
    expect((within(reopened).getByRole("radio", { name: "Follow system" }) as HTMLInputElement).checked).toBe(true);
  });
});
