import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApplicationMenu } from "@/components/ApplicationMenu";
import { ThemeProvider } from "@/components/theme-provider";

const auth = vi.hoisted(() => ({ isAuthenticated: true, member: null, logout: vi.fn() }));
vi.mock("@/auth/AuthContext", () => ({ useAuth: () => auth }));
beforeEach(() => localStorage.clear());
afterEach(() => { cleanup(); auth.isAuthenticated = true; vi.clearAllMocks(); document.documentElement.className = ""; });

function Location() {
  const location = useLocation();
  return <p>{location.pathname + location.search}</p>;
}
function mount(path = "/") {
  render(<ThemeProvider defaultTheme="light"><MemoryRouter initialEntries={[path]}><ApplicationMenu /><Location /></MemoryRouter></ThemeProvider>);
  fireEvent.keyDown(screen.getByRole("button", { name: "Application menu" }), { key: "Enter" });
}

describe("shared application menu", () => {
  it("logs out and returns to sign-in immediately", async () => {
    mount();
    fireEvent.click(screen.getByRole("menuitem", { name: "Logout" }));
    expect(auth.logout).toHaveBeenCalledOnce();
    expect(await screen.findByText("/login")).toBeTruthy();
  });

  it.each(["/", "/sources", "/anomalies", "/details/entity-one"])("offers shared preferences and system status at %s", (path) => {
    mount(path);
    expect(screen.getAllByRole("menuitem").map(item => item.textContent)).toEqual(["Account", "Settings", "System status", "Logout"]);
  });

  it.each([["/account", "Account"], ["/system/status", "System status"]])("marks the current page at %s", (path, label) => {
    mount(path);
    expect(screen.getByRole("menuitem", { name: label }).getAttribute("aria-current")).toBe("page");
  });

  it("offers sign-in without authenticated application actions", () => {
    auth.isAuthenticated = false;
    render(<MemoryRouter><ApplicationMenu /></MemoryRouter>);
    expect(screen.getByRole("link", { name: "Login" }).getAttribute("href")).toBe("/login");
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
    fireEvent.click(screen.getByRole("menuitem", { name: "Settings" }));
    const dialog = await screen.findByRole("dialog", { name: "Settings" });
    expect(screen.getByText(path)).toBeTruthy();
    expect(within(dialog).getByRole("tab", { name: "Appearance" }).getAttribute("aria-selected")).toBe("true");
    expect(within(dialog).queryByText("Collection diagnostics")).toBeNull();
    expect((within(dialog).getByRole("radio", { name: "Light" }) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(within(dialog).getByRole("radio", { name: "Dark" }));
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(localStorage.getItem("vite-ui-theme")).toBe("dark");
    expect((within(dialog).getByRole("radio", { name: "Dark" }) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(within(dialog).getByRole("button", { name: "Close settings" }));
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Application menu" })));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByText(path)).toBeTruthy();
  });

  it("closes preferences with Escape and reopens the saved choice", async () => {
    mount();
    fireEvent.click(screen.getByRole("menuitem", { name: "Settings" }));
    const dialog = await screen.findByRole("dialog", { name: "Settings" });
    fireEvent.click(within(dialog).getByRole("radio", { name: "Follow system" }));
    expect(localStorage.getItem("vite-ui-theme")).toBe("system");
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    fireEvent.keyDown(screen.getByRole("button", { name: "Application menu" }), { key: "Enter" });
    fireEvent.click(screen.getByRole("menuitem", { name: "Settings" }));
    const reopened = await screen.findByRole("dialog", { name: "Settings" });
    expect((within(reopened).getByRole("radio", { name: "Follow system" }) as HTMLInputElement).checked).toBe(true);
  });
});
