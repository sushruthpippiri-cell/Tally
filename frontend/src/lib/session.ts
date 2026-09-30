/** The access token lives in this module's memory only (D-051 #1): never in browser storage.
 * A reload loses it; the HttpOnly refresh cookie restores it (lib/auth.ts). */
let accessToken: string | null = null;
const listeners = new Set<() => void>();

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
  listeners.forEach((listener) => listener());
}

export function onSessionChange(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
