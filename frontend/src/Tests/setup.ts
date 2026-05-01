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
  for (const target of [globalThis, window]) {
    Object.defineProperty(target, storageName, {
      configurable: true,
      value: storage,
      writable: true,
    });
  }
};

bindTestStorage("localStorage", createTestStorage());
bindTestStorage("sessionStorage", createTestStorage());
