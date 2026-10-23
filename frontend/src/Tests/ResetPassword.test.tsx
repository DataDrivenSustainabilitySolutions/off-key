import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { clientLogger } from "@/lib/logger";
import ResetPassword from "@/pages/ResetPassword";

const fetchMock = vi.fn<typeof fetch>();

const PASSWORD = "a-long-enough-password";

function renderAt(entry: string) {
  render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="/login" element={<p>Login page</p>} />
        <Route path="/forgot-password" element={<p>Forgot password page</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

function submit(password = PASSWORD, confirmation = password) {
  fireEvent.change(screen.getByLabelText("New password"), {
    target: { value: password },
  });
  fireEvent.change(screen.getByLabelText("Confirm password"), {
    target: { value: confirmation },
  });
  fireEvent.click(screen.getByRole("button", { name: "Reset password" }));
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

describe("ResetPassword", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  it("explains an incomplete link and offers a new one instead of the form", () => {
    renderAt("/reset-password");

    expect(screen.getByRole("alert").textContent).toContain(
      "This reset link is incomplete",
    );
    expect(screen.queryByLabelText("New password")).toBeNull();
    fireEvent.click(screen.getByRole("link", { name: "Request a new link" }));
    expect(screen.getByText("Forgot password page")).toBeTruthy();
  });

  it.each([
    ["short", "too-short", "too-short", "Password must be at least"],
    ["mismatched", PASSWORD, `${PASSWORD}!`, "Passwords do not match"],
  ])(
    "rejects a %s password without contacting the server",
    (_, password, confirmation, message) => {
      renderAt("/reset-password#token=reset-token");

      submit(password, confirmation);

      expect(screen.getByRole("alert").textContent).toContain(message);
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

  it("sends the token from the fragment and returns to login after success", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fetchMock.mockResolvedValueOnce(json(200, { message: "ok" }));
    renderAt("/reset-password#token=reset-token");

    submit();

    expect((await screen.findByRole("status")).textContent).toContain(
      "Password successfully reset",
    );
    expect(screen.queryByLabelText("New password")).toBeNull();
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/api/v1/auth/reset-password");
    expect(init).toMatchObject({ method: "POST" });
    expect(JSON.parse(init!.body as string)).toEqual({
      token: "reset-token",
      new_password: PASSWORD,
    });

    await act(async () => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.getByText("Login page")).toBeTruthy();
  });

  it("shows the server's reason and keeps the form for another attempt", async () => {
    fetchMock.mockResolvedValueOnce(json(400, { detail: "Reset link expired" }));
    renderAt("/reset-password#token=reset-token");

    submit();

    expect((await screen.findByRole("alert")).textContent).toBe(
      "Reset link expired",
    );
    expect(screen.getByLabelText("New password")).toBeTruthy();
  });

  it("reports unreachable servers and logs the failure", async () => {
    const logError = vi.spyOn(clientLogger, "error").mockImplementation(() => {});
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    renderAt("/reset-password#token=reset-token");

    submit();

    expect((await screen.findByRole("alert")).textContent).toBe(
      "Server error. Please try again later.",
    );
    expect(logError).toHaveBeenCalledWith(
      expect.objectContaining({ event: "auth.reset_password_request_failed" }),
    );
  });
});
