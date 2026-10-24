import { describe, expect, it, vi } from "vitest";
import { ApiClient } from "../src/lib/api";

function json(data: unknown, status = 200) { return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } }); }
function fakeFetch() {
  return vi.fn<typeof fetch>().mockImplementation(async (url) => url === "/api/v1/session"
    ? json({ request_id: "session", data: { csrf_token: "test-csrf" } })
    : json({ request_id: "request", data: [] }));
}

describe("authenticated API adapter", () => {
  it("shares session bootstrap and sends credentialed requests", async () => {
    const fetcher = fakeFetch(), api = new ApiClient(fetcher);
    await Promise.all([api.projects(), api.projects()]);
    expect(fetcher.mock.calls.filter(([url]) => url === "/api/v1/session")).toHaveLength(1);
    for (const [, options] of fetcher.mock.calls) expect(options?.credentials).toBe("include");
  });
  it("retains explicit mutation intent and never retries a write automatically", async () => {
    const fetcher = fakeFetch(), api = new ApiClient(fetcher);
    await api.createProject("原始想法", "名称", "fixed-intent");
    const [, options] = fetcher.mock.calls[1]!;
    expect(options?.method).toBe("POST");
    expect(options?.headers).toMatchObject({ "X-CSRF-Token": "test-csrf", "Idempotency-Key": "fixed-intent" });
    expect(JSON.parse(options!.body as string)).toEqual({ original_idea: "原始想法", title: "名称" });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it("propagates stable errors with request IDs, without echoing raw input", async () => {
    const fetcher = fakeFetch();
    fetcher.mockImplementationOnce(async () => json({ data: { csrf_token: "csrf" } }));
    fetcher.mockImplementationOnce(async () => json({ request_id: "r-1", error: { code: "IDEMPOTENCY_CONFLICT", message: "请求内容冲突" } }, 409));
    await expect(new ApiClient(fetcher).createProject("private idea", "x", "key"))
      .rejects.toMatchObject({ code: "IDEMPOTENCY_CONFLICT", requestId: "r-1", message: "请求内容冲突" });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it("preserves session expiry as an error rather than silently creating a new identity", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(json({ error: { code: "SESSION_EXPIRED", message: "会话过期" } }, 401));
    await expect(new ApiClient(fetcher).projects()).rejects.toMatchObject({ code: "SESSION_EXPIRED" });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("carries AbortSignal to preview and does not turn cancellation into an error", async () => {
    const fetcher = fakeFetch(), api = new ApiClient(fetcher), controller = new AbortController();
    const { draft } = await import("../src/lib/model");
    const scene = draft("retail_perishable", { id: "p", title: "x", original_idea: "x", created_at: "now" }, true);
    await api.preview("project", scene, "low", controller.signal);
    const [, options] = fetcher.mock.calls[1]!;
    expect(options?.signal).toBe(controller.signal);
    expect(options?.headers).not.toHaveProperty("Idempotency-Key");
    expect(JSON.parse(options!.body as string).scene).toEqual(scene);
  });
  it("maps bootstrap network failure and malformed responses into recoverable errors", async () => {
    await expect(new ApiClient(vi.fn<typeof fetch>().mockRejectedValue(new TypeError("offline"))).projects())
      .rejects.toMatchObject({ code: "NETWORK_UNAVAILABLE" });
    await expect(new ApiClient(vi.fn<typeof fetch>().mockImplementation(async () => json(null))).projects())
      .rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });
});
