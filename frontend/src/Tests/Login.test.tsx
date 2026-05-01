import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

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

let fetchMock: ReturnType<typeof vi.fn>;
let originalFetch: typeof global.fetch;

beforeEach(() => {
  originalFetch = global.fetch;
  fetchMock = vi.fn();
  global.fetch = fetchMock as typeof fetch;
  localStorage.clear();
  sessionStorage.clear();
  mockNavigate.mockReset();
});

afterEach(() => {
  global.fetch = originalFetch;
  vi.resetAllMocks();
});

const renderLogin = () =>
  render(
    <AuthProvider>
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    </AuthProvider>
  );

describe("Login", () => {
  it("shows form fields and submit button", () => {
    renderLogin();

    expect(screen.getByLabelText(/e-mail/i)).toBeTruthy();
    expect(
      screen.getByLabelText(/password/i, { selector: "input" })
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: /log in/i })).toBeTruthy();
  });

  it("shows an error message for invalid credentials", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Test-Fehler" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      })
    );

    renderLogin();
    fireEvent.change(screen.getByLabelText(/e-mail/i), {
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

  it("stores the token and navigates after a successful login", async () => {
    const mockToken = "abc123";

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
    fireEvent.change(screen.getByLabelText(/e-mail/i), {
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
