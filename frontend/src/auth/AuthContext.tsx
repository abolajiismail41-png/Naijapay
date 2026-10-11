import { useQueryClient } from "@tanstack/react-query";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, session, type TokenPair } from "../lib/api";
import type { Me } from "../lib/types";

interface AuthState {
  status: "loading" | "anon" | "authed";
  me: Me | null;
  signIn: (t: TokenPair) => Promise<Me>;
  signOut: () => Promise<void>;
  refreshMe: () => Promise<void>;
}
const Ctx = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [status, setStatus] = useState<AuthState["status"]>("loading");
  const [me, setMe] = useState<Me | null>(null);

  const drop = useCallback(() => { setMe(null); setStatus("anon"); qc.clear(); }, [qc]);

  useEffect(() => {
    session.onAuthLost(drop);
    if (!session.hasRefresh()) { setStatus("anon"); return; }
    api.get<Me>("/api/v1/users/me").then((m) => { setMe(m); setStatus("authed"); }).catch(() => { session.setTokens(null); setStatus("anon"); });
  }, [drop]);

  const signIn = useCallback(async (t: TokenPair) => {
    session.setTokens(t);
    const m = await api.get<Me>("/api/v1/users/me");
    setMe(m); setStatus("authed");
    return m;
  }, []);

  const signOut = useCallback(async () => {
    try { await api.post("/api/v1/auth/logout"); } catch { /* signing out locally regardless */ }
    session.setTokens(null);
    drop();
  }, [drop]);

  const refreshMe = useCallback(async () => { setMe(await api.get<Me>("/api/v1/users/me")); }, []);

  const value = useMemo(() => ({ status, me, signIn, signOut, refreshMe }), [status, me, signIn, signOut, refreshMe]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
