import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { setAccessToken } from "../lib/session";
import { api, ApiError, setRefresher } from "./client";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  setAccessToken(null);
  setRefresher(null);
});
afterAll(() => server.close());

describe("api", () => {
  it("sends the in-memory bearer token to /api and keeps money as strings", async () => {
    setAccessToken("t-1");
    server.use(
      http.get("*/api/companies/c-1/analytics/sales", ({ request }) =>
        HttpResponse.json({
          auth: request.headers.get("authorization"),
          query: new URL(request.url).search,
          total: "12345678.9000",
        }),
      ),
    );
    const body = await api<{ auth: string; query: string; total: string }>(
      "/companies/c-1/analytics/sales",
      { query: { from: "2026-04-01", to: null } },
    );
    expect(body).toEqual({ auth: "Bearer t-1", query: "?from=2026-04-01", total: "12345678.9000" });
  });

  it("maps an error body to ApiError(code, message)", async () => {
    server.use(
      http.post("*/api/companies/c-1/sync", () =>
        HttpResponse.json(
          { code: "AGENT_SELECTION_REQUIRED", message: "choose one", details: null },
          { status: 422 },
        ),
      ),
    );
    const error: unknown = await api("/companies/c-1/sync", { method: "POST", body: {} }).catch(
      (e: unknown) => e,
    );
    if (!(error instanceof ApiError)) throw new Error("expected an ApiError");
    expect([error.status, error.code, error.message]).toEqual([
      422,
      "AGENT_SELECTION_REQUIRED",
      "choose one",
    ]);
  });

  it("refreshes once after a 401 and retries", async () => {
    let calls = 0;
    server.use(
      http.get("*/api/companies", ({ request }) => {
        calls += 1;
        return request.headers.get("authorization") === "Bearer fresh"
          ? HttpResponse.json([])
          : HttpResponse.json({ code: "NOT_AUTHENTICATED", message: "expired" }, { status: 401 });
      }),
    );
    setRefresher(async () => {
      setAccessToken("fresh");
      return true;
    });
    await expect(api("/companies")).resolves.toEqual([]);
    expect(calls).toBe(2);
  });
});
