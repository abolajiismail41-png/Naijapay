import { createContext, type ReactNode, useCallback, useContext, useMemo, useState } from "react";

interface ToastItem { id: number; text: string; tone: "info" | "error" }
const Ctx = createContext<{ toast: (text: string, tone?: "info" | "error") => void }>({ toast: () => undefined });
export const useToast = () => useContext(Ctx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const toast = useCallback((text: string, tone: "info" | "error" = "info") => {
    const id = Date.now() + Math.random();
    setItems((xs) => [...xs.slice(-2), { id, text, tone }]);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), 5000);
  }, []);
  const value = useMemo(() => ({ toast }), [toast]);
  return (
    <Ctx.Provider value={value}>
      {children}
      <div className="toasts" aria-live="polite">{items.map((t) => <div key={t.id} className={`toast ${t.tone === "error" ? "error" : ""}`}>{t.text}</div>)}</div>
    </Ctx.Provider>
  );
}
