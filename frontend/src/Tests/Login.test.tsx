import { act, render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";

import { AuthProvider } from "@/auth/AuthContext";
import { tokenManager } from "@/lib/api-client";
import Login from "../pages/Login";

const mockNavigate = vi.fn();

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>(
    "react-router-dom"
  );

  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

let fetchMock: Mock<typeof fetch>;
let originalFetch: typeof globalThis.fetch;

beforeEach(() => {
  originalFetch = globalThis.fetch;
  fetchMock = vi.fn<typeof fetch>();
  globalThis.fetch = fetchMock;
  localStorage.clear();
  sessionStorage.clear();
  mockNavigate.mockReset();
  vi.stubEnv("VITE_LOCAL_ADMIN_EMAIL", undefined);
  vi.stubGlobal("location", { hostname: "localhost" });
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.resetAllMocks();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

const renderLogin = () =>
  render(
    <AuthProvider>
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    </AuthProvider>
  );

const encodeBase64Url = (value: object): string =>
  btoa(JSON.stringify(value))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");

const createUnsignedToken = (payload: object): string =>
  [
    encodeBase64Url({ alg: "none", typ: "JWT" }),
    encodeBase64Url(payload),
    "",
  ].join(".");

describe("Login", () => {
  it("shows form fields and submit button", () => {
    renderLogin();

    expect(screen.getByLabelText(/email/i)).toBeTruthy();
    expect(
      screen.getByLabelText(/password/i, { selector: "input" })
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: /log in/i })).toBeTruthy();
  });

  it.each(["127.0.0.1", "localhost", "[::1]", "::1"])(
    "submits the configured email for the local admin alias on %s",
    async (hostname) => {
      vi.stubEnv("VITE_LOCAL_ADMIN_EMAIL", "admin@example.com");
      vi.stubGlobal("location", { hostname });
      fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Invalid credentials" }), {
        status: 401, headers: { "Content-Type": "application/json" },
      }));
      renderLogin();

      const email = screen.getByLabelText("Email") as HTMLInputElement;
      const password = screen.getByLabelText(/password/i, { selector: "input" }) as HTMLInputElement;
      expect(email.type).toBe("text");
      expect(email.placeholder).toBe("Email");
      expect(email.inputMode).toBe("email");
      expect(email.autocomplete).toBe("username");
      expect(password.autocomplete).toBe("current-password");
      fireEvent.change(email, { target: { value: "admin" } });
      fireEvent.change(password, { target: { value: "admin" } });
      fireEvent.click(screen.getByRole("button", { name: /log in/i }));

      await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
      expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({
        email: "admin@example.com", password: "admin", remember_me: false,
      });
      expect(await screen.findByText("Invalid credentials")).toBeTruthy();
    },
  );

  it.each([
    { hostname: "localhost", configuredEmail: undefined },
    { hostname: "app.example.com", configuredEmail: "admin@example.com" },
    { hostname: "127.0.0.1.example.com", configuredEmail: "admin@example.com" },
    { hostname: "localhost", configuredEmail: "invalid-email" },
  ])("keeps email login and rejects the alias with $hostname/$configuredEmail", ({ hostname, configuredEmail }) => {
    vi.stubEnv("VITE_LOCAL_ADMIN_EMAIL", configuredEmail);
    vi.stubGlobal("location", { hostname });
    renderLogin();
    const email = screen.getByLabelText("Email") as HTMLInputElement;
    expect(email.type).toBe("email");
    fireEvent.change(email, { target: { value: "admin" } });
    fireEvent.change(screen.getByLabelText(/password/i, { selector: "input" }), { target: { value: "admin" } });
    fireEvent.submit(screen.getByRole("button", { name: /log in/i }).closest("form")!);
    expect(screen.getByText("Please enter a valid email address")).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("only maps the exact admin alias when local login is enabled", () => {
    vi.stubEnv("VITE_LOCAL_ADMIN_EMAIL", "admin@example.com");
    renderLogin();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "administrator" } });
    fireEvent.change(screen.getByLabelText(/password/i, { selector: "input" }), { target: { value: "admin" } });
    fireEvent.click(screen.getByRole("button", { name: /log in/i }));
    expect(screen.getByText("Please enter a valid email address")).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each(["response", "network"])("blocks duplicate submissions and allows retry after a %s failure", async failure => {
    let complete!: (response: Response) => void;
    let fail!: (error: Error) => void;
    fetchMock.mockReturnValueOnce(new Promise<Response>((resolve, reject) => { complete = resolve; fail = reject; }));
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Retry rejected" }), {
      status: 401, headers: { "Content-Type": "application/json" },
    }));
    renderLogin();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "test@example.com" } });
    fireEvent.change(screen.getByLabelText("Password", { selector: "input" }), { target: { value: "wrongpass" } });
    const form = screen.getByRole("button", { name: "Log in" }).closest("form")!;
    fireEvent.submit(form);
    fireEvent.submit(form);
    const pending = screen.getByRole("button", { name: "Logging in…" }) as HTMLButtonElement;
    expect(pending.disabled).toBe(true);
    expect(pending.getAttribute("aria-busy")).toBe("true");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    fireEvent.submit(form);
    expect(fetchMock).toHaveBeenCalledOnce();
    await act(async () => {
      if (failure === "network") fail(new Error("Network unavailable"));
      else complete(new Response(JSON.stringify({ detail: "Invalid credentials" }), {
        status: 401, headers: { "Content-Type": "application/json" },
      }));
    });
    expect(screen.getByText(failure === "network" ? "An error occurred" : "Invalid credentials")).toBeTruthy();
    const ready = screen.getByRole("button", { name: "Log in" }) as HTMLButtonElement;
    expect(ready.disabled).toBe(false);
    expect(ready.getAttribute("aria-busy")).toBe("false");
    fireEvent.submit(form);
    await screen.findByText("Retry rejected");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect((screen.getByRole("button", { name: "Log in" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("shows an error message for invalid credentials", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Test-Fehler" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      })
    );

    renderLogin();
    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "test@example.com" },
    });
    fireEvent.change(screen.getByLabelText(/password/i, { selector: "input" }), {
      target: { value: "wrongpass" },
    });
    fireEvent.click(screen.getByRole("button", { name: /log in/i }));

    await waitFor(() => {
      expect(screen.getByText(/test-fehler/i)).toBeTruthy();
    });
  });

  it.each([false, true])("submits and persists the remember setting %s after login", async (rememberMe) => {
    const mockToken = createUnsignedToken({
      sub: "test@example.com",
      user_id: 7,
      exp: Math.floor(Date.now() / 1000) + 3600,
    });

    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          access_token: mockToken,
          token_type: "bearer",
          user_id: 7,
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }
      )
    );

    renderLogin();
    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "test@example.com" },
    });
    fireEvent.change(screen.getByLabelText(/password/i, { selector: "input" }), {
      target: { value: "correctpass" },
    });
    if (rememberMe) fireEvent.click(screen.getByLabelText("Remember this device"));
    fireEvent.click(screen.getByRole("button", { name: /log in/i }));

    await waitFor(() => {
      expect(tokenManager.getToken()).toBe(mockToken);
    });
    expect(mockNavigate).toHaveBeenCalledWith("/");
    expect(fetchMock.mock.calls[0]?.[1]?.credentials).toBe("include");
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body)).remember_me).toBe(rememberMe);
    // Remembered access tokens stay in memory; only the HttpOnly cookie persists.
    expect(localStorage.getItem("auth_token")).toBeNull();
    expect(sessionStorage.getItem("auth_token")).toBe(rememberMe ? null : mockToken);
    expect(tokenManager.isRemembered()).toBe(rememberMe);
  });

  it("accepts a valid login response even when the token has no user id claim", async () => {
    const mockToken = createUnsignedToken({
      sub: "test@example.com",
      exp: Math.floor(Date.now() / 1000) + 3600,
    });
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ access_token: mockToken, token_type: "bearer" }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }
      )
    );

    renderLogin();
    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "test@example.com" },
    });
    fireEvent.change(screen.getByLabelText(/password/i, { selector: "input" }), {
      target: { value: "correctpass" },
    });
    fireEvent.click(screen.getByRole("button", { name: /log in/i }));

    await waitFor(() => {
      expect(tokenManager.getToken()).toBe(mockToken);
    });
    expect(mockNavigate).toHaveBeenCalledWith("/");
  });
});
