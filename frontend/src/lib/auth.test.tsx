import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../test/render";
import { server, withMockApi } from "../test/server";
import { handleMessage, login, logout, refresh } from "./auth";
import { getAccessToken, setAccessToken } from "./session";
import { resetRestore } from "./useSession";

withMockApi();
afterEach(() => {
  setAccessToken(null);
  resetRestore();
  vi.unstubAllGlobals();
});

function refreshes(answer: () => Response): { calls: Request[] } {
  const seen = { calls: [] as Request[] };
  server.use(
    http.post("*/api/auth/refresh", ({ request }) => {
      seen.calls.push(request);
      return answer();
    }),
  );
  return seen;
}

describe("the access token lives in memory only (D-051 #1)", () => {
  it("login keeps it in memory and writes nothing to browser storage", async () => {
    server.use(
      http.post("*/api/auth/login", () =>
        HttpResponse.json({ access_token: "a1", token_type: "bearer", expires_in: 1800 }),
      ),
    );
    await login("owner@example.com", "correct horse");
    expect(getAccessToken()).toBe("a1");
    expect([window.localStorage.length, window.sessionStorage.length]).toEqual([0, 0]);
  });
});

describe("refresh (D-051 #1-3)", () => {
  it("asks with the CSRF header and the cookie, never a token in the body", async () => {
    const seen = refreshes(() => HttpResponse.json({ access_token: "a2", expires_in: 1800 }));
    await expect(refresh()).resolves.toBe(true);
    const [request] = seen.calls;
    expect(request?.headers.get("x-tally-request")).toBe("1");
    expect(await request?.text()).toBe("");
    expect(getAccessToken()).toBe("a2");
  });

  it("signs out when the cookie is refused", async () => {
    setAccessToken("old");
    refreshes(() => HttpResponse.json({ code: "NOT_AUTHENTICATED" }, { status: 401 }));
    await expect(refresh()).resolves.toBe(false);
    expect(getAccessToken()).toBeNull();
  });

  it("makes one request for simultaneous refreshes in a tab", async () => {
    const seen = refreshes(() => HttpResponse.json({ access_token: "a3", expires_in: 1800 }));
    await Promise.all([refresh(), refresh(), refresh()]);
    expect(seen.calls).toHaveLength(1);
  });

  it("waits for another tab's refresh and uses its token instead of spending the cookie", async () => {
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => (release = resolve));
    vi.stubGlobal("navigator", {
      ...navigator,
      locks: {
        // another tab holds the lock until `release`
        request: async (_name: string, run: () => Promise<boolean>) => {
          await held;
          return run();
        },
      },
    });
    const seen = refreshes(() => HttpResponse.json({ access_token: "mine", expires_in: 1800 }));
    const pending = refresh();
    handleMessage({ type: "token", token: "from-the-other-tab", at: Date.now() + 1 });
    release();
    await expect(pending).resolves.toBe(true);
    expect(seen.calls).toHaveLength(0);
    expect(getAccessToken()).toBe("from-the-other-tab");
  });
});

describe("a page load", () => {
  const app = (path: string) => renderApp(path, { signedIn: false });

  it("restores the session from the cookie", async () => {
    refreshes(() => HttpResponse.json({ access_token: "a4", expires_in: 1800 }));
    server.use(http.get("*/api/companies", () => HttpResponse.json([])));
    app("/companies");
    expect(await screen.findByRole("heading", { name: "Companies" })).toBeInTheDocument();
  });

  it("goes to sign-in when there is no session", async () => {
    refreshes(() => HttpResponse.json({ code: "NOT_AUTHENTICATED" }, { status: 401 }));
    app("/companies");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });
});

describe("logout", () => {
  it("closes the session on the server and forgets the token", async () => {
    setAccessToken("a5");
    let header: string | null = null;
    server.use(
      http.post("*/api/auth/logout", ({ request }) => {
        header = request.headers.get("x-tally-request");
        return new HttpResponse(null, { status: 204 });
      }),
    );
    await logout();
    expect(header).toBe("1");
    expect(getAccessToken()).toBeNull();
  });
});
