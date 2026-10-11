const mem = new Map<string, string>();

function ls(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** localStorage with an in-memory fallback (private mode, tests). */
export const store = {
  get(key: string): string | null {
    try {
      const s = ls();
      return s ? s.getItem(key) : (mem.get(key) ?? null);
    } catch {
      return mem.get(key) ?? null;
    }
  },
  set(key: string, value: string): void {
    try {
      const s = ls();
      if (s) s.setItem(key, value);
      else mem.set(key, value);
    } catch {
      mem.set(key, value);
    }
  },
  remove(key: string): void {
    try {
      ls()?.removeItem(key);
    } catch {
      /* ignore */
    }
    mem.delete(key);
  },
};
