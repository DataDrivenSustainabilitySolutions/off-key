import { configure } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// A lazily loaded view appears no sooner than React's 300 ms Suspense fallback
// throttle, its first import also transforms its module graph, and CI runs
// several jsdom workers on one shared runner, so the 1 s default fails there
// although the view renders. A wait still ends as soon as its element appears,
// and stays under Vitest's 5 s test timeout so a failure reports the DOM.
configure({ asyncUtilTimeout: 4_000 });

const createTestStorage = (): Storage => {
  const entries = new Map<string, string>();

  return {
    get length() {
      return entries.size;
    },
    clear: () => {
      entries.clear();
    },
    getItem: (key: string) => entries.get(key) ?? null,
    key: (index: number) => Array.from(entries.keys())[index] ?? null,
    removeItem: (key: string) => {
      entries.delete(key);
    },
    setItem: (key: string, value: string) => {
      entries.set(key, value);
    },
  };
};

const bindTestStorage = (
  storageName: "localStorage" | "sessionStorage",
  storage: Storage
) => {
  for (const target of typeof window === "undefined" ? [globalThis] : [globalThis, window]) {
    Object.defineProperty(target, storageName, {
      configurable: true,
      value: storage,
      writable: true,
    });
  }
};

bindTestStorage("localStorage", createTestStorage());
bindTestStorage("sessionStorage", createTestStorage());

class TestResizeObserver implements ResizeObserver {
  disconnect() {}
  observe() {}
  unobserve() {}
}

Object.defineProperty(globalThis, "ResizeObserver", {
  configurable: true,
  value: TestResizeObserver,
  writable: true,
});

if (typeof window !== "undefined") {
  // A light-scheme, no-preference default; tests needing a match stub their own.
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (media: string) => ({
      matches: false,
      media,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

afterEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  vi.useRealTimers();
});
