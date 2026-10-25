import { afterEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "./api";

describe("apiFetch", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it("attaches a fresh bearer token to each request", async () => {
    vi.stubEnv("NEXT_PUBLIC_BACKEND_URL", "https://api.example.test");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    const getToken = vi.fn().mockResolvedValue("session-jwt");

    await expect(apiFetch(getToken, "/api/keys")).resolves.toEqual({ ok: true });

    expect(getToken).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][1]?.headers).toBeInstanceOf(Headers);
    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).get("Authorization")).toBe("Bearer session-jwt");
  });

  it("refreshes the token once after a 401 and retries", async () => {
    vi.stubEnv("NEXT_PUBLIC_BACKEND_URL", "https://api.example.test");
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({ error: "authentication_required" }), { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    const getToken = vi.fn()
      .mockResolvedValueOnce("expired")
      .mockResolvedValueOnce("fresh");

    await expect(apiFetch(getToken, "/api/keys")).resolves.toEqual({ ok: true });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(getToken).toHaveBeenNthCalledWith(2, { skipCache: true });
    expect(new Headers(fetchMock.mock.calls[1][1]?.headers).get("Authorization")).toBe("Bearer fresh");
  });

  it("redirects to sign-in after a second 401", async () => {
    vi.stubEnv("NEXT_PUBLIC_BACKEND_URL", "https://api.example.test");
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify({ error: "authentication_required" }), { status: 401 }));
    const getToken = vi.fn().mockResolvedValueOnce("expired").mockResolvedValueOnce("still-expired");
    const onUnauthenticated = vi.fn();

    await expect(apiFetch(getToken, "/api/keys", {}, onUnauthenticated)).rejects.toMatchObject({
      code: "authentication_required",
      status: 401,
    });

    expect(getToken).toHaveBeenCalledTimes(2);
    expect(onUnauthenticated).toHaveBeenCalledTimes(1);
  });

  it("maps no_api_key to a clear actionable error", async () => {
    vi.stubEnv("NEXT_PUBLIC_BACKEND_URL", "https://api.example.test");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: false, error: "no_api_key" }), { status: 400 }),
    );

    await expect(apiFetch(vi.fn().mockResolvedValue("token"), "/api/agent")).rejects.toMatchObject({
      code: "no_api_key",
      status: 400,
      message: "Add an AI provider key in Settings to start chatting.",
    });
  });
});
