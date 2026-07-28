import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { ThemeProvider, useTheme } from "../components/theme-provider";

const STORAGE_KEY = "theme-provider-test";

function ThemeControls() {
  const { theme, setTheme } = useTheme();
  return (
    <>
      <output>{theme}</output>
      <button type="button" onClick={() => setTheme("dark")}>
        Use dark theme
      </button>
    </>
  );
}

describe("ThemeProvider", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove("dark", "light");
  });

  it("ignores invalid persisted theme values", () => {
    localStorage.setItem(STORAGE_KEY, "invalid");

    render(
      <ThemeProvider defaultTheme="light" storageKey={STORAGE_KEY}>
        <ThemeControls />
      </ThemeProvider>
    );

    expect(screen.getByText("light")).toBeTruthy();
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
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });
});
