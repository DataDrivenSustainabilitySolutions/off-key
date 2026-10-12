import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApplicationMenu } from "@/components/ApplicationMenu";

const auth = vi.hoisted(() => ({ isAuthenticated: true, member: null, logout: vi.fn() }));
vi.mock("@/auth/AuthContext", () => ({ useAuth: () => auth }));
afterEach(() => { cleanup(); auth.isAuthenticated = true; vi.clearAllMocks(); });

function Location() {
  return <p>{useLocation().pathname}</p>;
}
function mount(path = "/") {
  render(<MemoryRouter initialEntries={[path]}><ApplicationMenu navigation /><Location /></MemoryRouter>);
  fireEvent.keyDown(screen.getByRole("button", { name: "Application menu" }), { key: "Enter" });
}

describe("shared application menu", () => {
  it("logs out and returns to sign-in immediately", async () => {
    mount();
    fireEvent.click(screen.getByRole("menuitem", { name: "Logout" }));
    expect(auth.logout).toHaveBeenCalledOnce();
    expect(await screen.findByText("/login")).toBeTruthy();
  });

  it.each(["/entities", "/details/entity-one", "/monitoring/entity-one"])("marks the entity directory current from %s while home points to monitoring", async (path) => {
    mount(path);
    expect(screen.getByRole("menuitem", { name: "Entities" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("menuitem", { name: "Monitoring" }).getAttribute("aria-current")).toBeNull();
    expect(screen.queryByRole("menuitem", { name: "Stations" })).toBeNull();
    fireEvent.click(screen.getByRole("menuitem", { name: "Monitoring" }));
    expect(await screen.findByText("/")).toBeTruthy();
  });

  it("opens the generic entity directory from the workspace menu", async () => {
    mount();
    fireEvent.click(screen.getByRole("menuitem", { name: "Entities" }));
    expect(await screen.findByText("/entities")).toBeTruthy();
  });

  it("offers sign-in without authenticated application actions", () => {
    auth.isAuthenticated = false;
    render(<MemoryRouter><ApplicationMenu navigation /></MemoryRouter>);
    expect(screen.getByRole("link", { name: "Login" }).getAttribute("href")).toBe("/login");
    expect(screen.queryByRole("button", { name: "Application menu" })).toBeNull();
  });

  it("links directly to the existing account settings", async () => {
    mount();
    fireEvent.click(screen.getByRole("menuitem", { name: "Settings" }));
    expect(await screen.findByText("/account/settings")).toBeTruthy();
  });
});
