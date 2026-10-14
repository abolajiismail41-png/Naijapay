import { API_BASE } from "../config";
import { store } from "./storage";

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    public requestId?: string,
    public details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface TokenPair { access_token: string; refresh_token: string; token_type: string; expires_in: number }

const REFRESH_KEY = "np.refresh";
const REQUEST_TIMEOUT_MS = 20_000;
/** For calls that wait on a slow upstream provider (e.g. SMS-Man price lookups and purchases). */
export const SLOW_REQUEST_TIMEOUT_MS = 90_000;
let access: string | null = null;
let refreshing: Promise<boolean> | null = null;
let authLost: (() => void) | null = null;

/** Access token lives in memory only; the refresh token is the one persisted credential. */
export const session = {
  setTokens(t: TokenPair | null): void {
    access = t?.access_token ?? null;
    if (t) store.set(REFRESH_KEY, t.refresh_token);
    else store.remove(REFRESH_KEY);
  },
  hasRefresh: (): boolean => store.get(REFRESH_KEY) !== null,
  onAuthLost(fn: () => void): void { authLost = fn; },
};

export interface Opts {
  query?: Record<string, string | number | boolean | null | undefined>;
  body?: unknown;
  headers?: Record<string, string>;
  auth?: boolean;
  idempotencyKey?: string;
  pinToken?: string;
  signal?: AbortSignal;
  /** Overrides the default 20s timeout. Use SLOW_REQUEST_TIMEOUT_MS for provider-backed calls. */
  timeoutMs?: number;
}

function url(path: string, query?: Opts["query"]): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query ?? {})) if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  const s = qs.toString();
  return `${API_BASE}${path}${s ? `?${s}` : ""}`;
}

async function send(method: string, path: string, o: Opts, token: string | null): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json", ...(o.headers ?? {}) };
  if (o.body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;
  if (o.idempotencyKey) headers["Idempotency-Key"] = o.idempotencyKey;
  if (o.pinToken) headers["X-PIN-Token"] = o.pinToken;
  const controller = new AbortController();
  const onCallerAbort = () => controller.abort(o.signal?.reason);
  if (o.signal?.aborted) onCallerAbort();
  else o.signal?.addEventListener("abort", onCallerAbort, { once: true });
  const timeoutMs = o.timeoutMs !== undefined && o.timeoutMs > 0 ? o.timeoutMs : REQUEST_TIMEOUT_MS;
  const timeout = setTimeout(() => controller.abort(new DOMException("Request timed out", "TimeoutError")), timeoutMs);
  try {
    return await fetch(url(path, o.query), {
      method, headers, signal: controller.signal, cache: "no-store",
      body: o.body === undefined ? undefined : JSON.stringify(o.body),
    });
  } catch (e) {
    if (o.signal?.aborted) throw e;
    if (controller.signal.aborted) {
      throw new ApiError("request_timeout", "The request took too long. Please check your connection and try again.", 0);
    }
    throw new ApiError("network_error", "We can't reach the server. Check your connection and try again.", 0);
  } finally {
    clearTimeout(timeout);
    o.signal?.removeEventListener("abort", onCallerAbort);
  }
}

async function parse<T>(res: Response): Promise<T> {
  const requestId = res.headers.get("x-request-id") ?? undefined;
  const text = await res.text();
  let body: any = null; // eslint-disable-line @typescript-eslint/no-explicit-any
  try { body = text ? JSON.parse(text) : null; } catch { /* handled below */ }
  if (res.ok && body && body.success === true) return body.data as T;
  const err = body?.error;
  if (err && typeof err.code === "string") throw new ApiError(err.code, err.message ?? "Something went wrong.", res.status, err.request_id ?? requestId, err.details);
  throw new ApiError("bad_response", res.status >= 500 ? "The service is having trouble. Please try again shortly." : "Unexpected response.", res.status, requestId);
}

function withLock<T>(fn: () => Promise<T>): Promise<T> {
  const locks = (typeof navigator !== "undefined" ? (navigator as any).locks : undefined); // eslint-disable-line @typescript-eslint/no-explicit-any
  return locks?.request ? locks.request("np-refresh", fn) : fn();
}

async function doRefresh(): Promise<boolean> {
  return withLock(async () => {
    const rt = store.get(REFRESH_KEY); // re-read inside the lock: another tab may have rotated it
    if (!rt) return false;
    try {
      const data = await parse<TokenPair>(await send("POST", "/api/v1/auth/refresh", { body: { refresh_token: rt } }, null));
      session.setTokens(data);
      return true;
    } catch (e) {
      if (e instanceof ApiError && e.status >= 400 && e.status < 500) session.setTokens(null); // definitively invalid
      return false; // a network blip keeps the refresh token
    }
  });
}

/** Single-flight: rotation + reuse detection means two parallel refreshes would sign the user out. */
export function refreshOnce(): Promise<boolean> {
  if (!refreshing) refreshing = doRefresh().finally(() => { refreshing = null; });
  return refreshing;
}

export async function request<T>(method: string, path: string, o: Opts = {}): Promise<T> {
  const auth = o.auth !== false;
  if (auth && !access && session.hasRefresh()) await refreshOnce();
  let res = await send(method, path, o, auth ? access : null);
  if (res.status === 401 && auth) {
    if (await refreshOnce()) res = await send(method, path, o, access);
    else authLost?.();
  }
  return parse<T>(res);
}

export const api = {
  get: <T>(path: string, query?: Opts["query"], o: Opts = {}) => request<T>("GET", path, { ...o, query }),
  post: <T>(path: string, body?: unknown, o: Opts = {}) => request<T>("POST", path, { ...o, body: body ?? {} }),
  patch: <T>(path: string, body?: unknown, o: Opts = {}) => request<T>("PATCH", path, { ...o, body: body ?? {} }),
  put: <T>(path: string, body?: unknown, o: Opts = {}) => request<T>("PUT", path, { ...o, body: body ?? {} }),
  del: <T>(path: string, o: Opts = {}) => request<T>("DELETE", path, o),
};

export function friendly(e: unknown): string {
  if (e instanceof ApiError) {
    const ref = e.requestId && (e.status >= 500 || e.code === "internal_error") ? ` (ref ${e.requestId.slice(0, 8)})` : "";
    return `${e.message}${ref}`;
  }
  return "Something went wrong. Please try again.";
}