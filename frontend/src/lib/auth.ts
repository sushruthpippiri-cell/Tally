import { api, API_BASE, setRefresher } from "../api/client";
import type { Schemas } from "../api/types";
import { getAccessToken, setAccessToken } from "./session";

/** Browser sessions (D-051 #1-3).
 *
 * - The access token is kept in memory (lib/session.ts); nothing goes to browser storage.
 * - The refresh token is an HttpOnly, Secure, SameSite=Strict cookie scoped to /api/auth: this
 *   code never sees it; the browser sends it to /api/auth/refresh and /api/auth/logout, which
 *   also need the `X-Tally-Request` header (CSRF, SEC-1.5).
 * - Tabs serialise refreshes with the Web Locks API and share a new access token over a
 *   BroadcastChannel: two tabs presenting the same rotated token would trip reuse detection
 *   (D-033 #4) and sign the user out everywhere. */

const CSRF_HEADERS = { "X-Tally-Request": "1" };
const LOCK = "tally-refresh";

type Message =
  { type: "token"; token: string; mustChange: boolean; at: number } | { type: "signed-out" };

const channel: BroadcastChannel | null =
  typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel("tally-auth");
let receivedAt = 0; // when another tab last handed us a fresh token
let inflight: Promise<boolean> | null = null;

/** Another tab's news (exported for tests). */
export function handleMessage(message: Message): void {
  if (message.type === "token") {
    receivedAt = message.at;
    setAccessToken(message.token, message.mustChange);
  } else {
    setAccessToken(null);
  }
}

if (channel) channel.onmessage = (event: MessageEvent<Message>) => handleMessage(event.data);

function signedIn({ access_token: token, must_change_password }: Schemas["TokenResponse"]): void {
  const mustChange = must_change_password ?? false;
  setAccessToken(token, mustChange);
  channel?.postMessage({ type: "token", token, mustChange, at: Date.now() } satisfies Message);
}

async function exchange(): Promise<boolean> {
  const response = await fetch(`${API_BASE}/auth/refresh`, {
    method: "POST",
    headers: CSRF_HEADERS,
    credentials: "same-origin",
  });
  if (!response.ok) {
    setAccessToken(null);
    return false;
  }
  signedIn((await response.json()) as Schemas["TokenResponse"]);
  return true;
}

/** A new access token from the refresh cookie. One refresh at a time in this tab, and one at a
 * time across tabs; a tab that waited while another refreshed uses that tab's token. */
export function refresh(): Promise<boolean> {
  if (inflight) return inflight;
  const askedAt = Date.now();
  const run = async (): Promise<boolean> =>
    receivedAt >= askedAt && getAccessToken() !== null ? true : exchange();
  const locks = typeof navigator === "undefined" ? undefined : navigator.locks;
  const serialised = async (): Promise<boolean> =>
    locks ? await locks.request(LOCK, run) : await run();
  const pending = serialised().finally(() => {
    inflight = null;
  });
  inflight = pending;
  return pending;
}

export async function login(email: string, password: string): Promise<void> {
  const body = await api<Schemas["TokenResponse"]>("/auth/login", {
    method: "POST",
    body: { email, password },
  });
  signedIn(body);
}

/** Every session closes, this tab's included; the API opens a new one for it (D-052). */
export async function changePassword(current: string, next: string): Promise<void> {
  const body = await api<Schemas["TokenResponse"]>("/auth/change-password", {
    method: "POST",
    body: { current_password: current, new_password: next },
  });
  signedIn(body);
}

export async function logout(): Promise<void> {
  try {
    await fetch(`${API_BASE}/auth/logout`, {
      method: "POST",
      headers: CSRF_HEADERS,
      credentials: "same-origin",
    });
  } finally {
    setAccessToken(null);
    channel?.postMessage({ type: "signed-out" } satisfies Message);
  }
}

setRefresher(refresh);
