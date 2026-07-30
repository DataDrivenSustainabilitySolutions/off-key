import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ThemeProvider, useTheme } from "../components/theme-provider";

const STORAGE_KEY = "theme-provider-test";

function ThemeControls() {
  const { theme, resolvedTheme, setTheme } = useTheme();
  return (
    <>
      <output aria-label="configured theme">{theme}</output>
      <output aria-label="resolved theme">{resolvedTheme}</output>
      <button type="button" onClick={() => setTheme("dark")}>
        Use dark theme
      </button>
    </>
  );
}

describe("ThemeProvider", () => {
  let prefersDark = false;
  let mediaListener: (() => void) | undefined;

  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove("dark", "light");
    prefersDark = false;
    mediaListener = undefined;
    vi.stubGlobal("matchMedia", () => ({
      get matches() {
        return prefersDark;
      },
      media: "(prefers-color-scheme: dark)",
      onchange: null,
      addEventListener: (_event: string, listener: () => void) => {
        mediaListener = listener;
      },
      removeEventListener: (_event: string, listener: () => void) => {
        if (mediaListener === listener) mediaListener = undefined;
      },
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
  });

  it("ignores invalid persisted theme values", () => {
    localStorage.setItem(STORAGE_KEY, "invalid");

    render(
      <ThemeProvider defaultTheme="light" storageKey={STORAGE_KEY}>
        <ThemeControls />
      </ThemeProvider>
    );

    expect(screen.getByLabelText("configured theme").textContent).toBe("light");
    expect(screen.getByLabelText("resolved theme").textContent).toBe("light");
    expect(document.documentElement.classList.contains("light")).toBe(true);
  });

  it("persists and applies explicit theme changes", () => {
    render(
      <ThemeProvider defaultTheme="light" storageKey={STORAGE_KEY}>
        <ThemeControls />
      </ThemeProvider>
    );

    fireEvent.click(screen.getByRole("button", { name: "Use dark theme" }));

    expect(localStorage.getItem(STORAGE_KEY)).toBe("dark");
    expect(screen.getByLabelText("resolved theme").textContent).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("tracks operating-system changes while configured as system", () => {
    render(
      <ThemeProvider defaultTheme="system" storageKey={STORAGE_KEY}>
        <ThemeControls />
      </ThemeProvider>,
    );

    expect(screen.getByLabelText("resolved theme").textContent).toBe("light");
    prefersDark = true;
    act(() => mediaListener?.());

    expect(screen.getByLabelText("configured theme").textContent).toBe("system");
    expect(screen.getByLabelText("resolved theme").textContent).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });
});
