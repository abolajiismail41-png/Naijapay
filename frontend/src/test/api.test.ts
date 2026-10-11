import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, session } from "../lib/api";

const ok = (data: unknown) => new Response(JSON.stringify({ success: true, data, message: "" }), { status: 200, headers: { "x-request-id": "req-1" } });
const fail = (status: number, code: string, message: string) => new Response(JSON.stringify({ success: false, error: { code, message, request_id: "req-9" } }), { status });
const pair = (a: string, r: string) => ({ access_token: a, refresh_token: r, token_type: "bearer", expires_in: 600 });

afterEach(() => { vi.unstubAllGlobals(); session.setTokens(null); });

describe("api client", () => {
  it("unwraps the success envelope and sends auth, idempotency and PIN headers", async () => {
    session.setTokens(pair("tok", "r1"));
    const spy = vi.fn(async () => ok({ hello: "world" }));
    vi.stubGlobal("fetch", spy);
    const out = await api.post<{ hello: string }>("/api/v1/x", { a: 1 }, { idempotencyKey: "k-123456789", pinToken: "pin-tok" });
    expect(out.hello).toBe("world");
    const [, init] = spy.mock.calls[0] as unknown as [string, RequestInit];
    const h = init.headers as Record<string, string>;
    expect(h.Authorization).toBe("Bearer tok");
    expect(h["Idempotency-Key"]).toBe("k-123456789");
    expect(h["X-PIN-Token"]).toBe("pin-tok");
    expect(init.body).toBe(JSON.stringify({ a: 1 }));
  });

  it("turns error envelopes into ApiError with the request id", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => fail(422, "insufficient_funds", "Your wallet balance is too low.")));
    await expect(api.get("/api/v1/x", undefined, { auth: false })).rejects.toMatchObject({ code: "insufficient_funds", status: 422, requestId: "req-9" });
  });

  it("maps network failures and non-JSON proxy errors", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("failed to fetch"); }));
    await expect(api.get("/api/v1/x", undefined, { auth: false })).rejects.toMatchObject({ code: "network_error", status: 0 });
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>bad gateway</html>", { status: 502 })));
    await expect(api.get("/api/v1/x", undefined, { auth: false })).rejects.toBeInstanceOf(ApiError);
  });

  it("refreshes exactly once when several requests hit an expired token at the same time", async () => {
    session.setTokens(pair("old", "r1"));
    let refreshes = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith("/api/v1/auth/refresh")) { refreshes += 1; return ok(pair("new", "r2")); }
      const auth = (init?.headers as Record<string, string>).Authorization;
      return auth === "Bearer new" ? ok({ n: 1 }) : fail(401, "unauthorized", "expired");
    }));
    const results = await Promise.all([api.get("/api/v1/a"), api.get("/api/v1/b"), api.get("/api/v1/c")]);
    expect(results).toEqual([{ n: 1 }, { n: 1 }, { n: 1 }]);
    expect(refreshes).toBe(1); // parallel refreshes would trip refresh-token reuse detection and sign the user out
  });

  it("keeps the refresh token through a network blip but drops it when the server rejects it", async () => {
    session.setTokens(pair("old", "r1"));
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/refresh")) throw new TypeError("offline");
      return fail(401, "unauthorized", "expired");
    }));
    await expect(api.get("/api/v1/a")).rejects.toBeInstanceOf(ApiError);
    expect(session.hasRefresh()).toBe(true);

    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => (String(input).endsWith("/refresh") ? fail(401, "unauthorized", "revoked") : fail(401, "unauthorized", "expired"))));
    await expect(api.get("/api/v1/a")).rejects.toBeInstanceOf(ApiError);
    expect(session.hasRefresh()).toBe(false);
  });
});
