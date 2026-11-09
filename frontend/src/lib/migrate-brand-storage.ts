/** Move saved preferences/drafts once; never overwrite newer state or lose a failed copy. */
export function migrateBrandStorage(storage: Storage) {
  const keys = Array.from({ length: storage.length }, (_, i) => storage.key(i));
  for (const key of keys) {
    if (!key || !(key.startsWith("off-key:draft:") || key === "off-key:details:chart-navigation")) continue;
    const target = key.replace("off-key:", "aberration:");
    const value = storage.getItem(key);
    if (value !== null && storage.getItem(target) === null) storage.setItem(target, value);
    storage.removeItem(key);
  }
}
