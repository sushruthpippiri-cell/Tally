/** The access token lives in this module's memory only (D-051 #1): never in browser storage.
 * A reload loses it; the HttpOnly refresh cookie restores it (lib/auth.ts). */
let accessToken: string | null = null;
/** D-052: signed in with an initial password; only choosing a new one is allowed. */
let mustChangePassword = false;
const listeners = new Set<() => void>();

export function getAccessToken(): string | null {
  return accessToken;
}

export function getMustChangePassword(): boolean {
  return mustChangePassword;
}

export function setAccessToken(token: string | null, mustChange = false): void {
  accessToken = token;
  mustChangePassword = token !== null && mustChange;
  listeners.forEach((listener) => listener());
}

/** The API refused a call with PASSWORD_CHANGE_REQUIRED (D-052). */
export function requirePasswordChange(): void {
  if (accessToken === null || mustChangePassword) return;
  mustChangePassword = true;
  listeners.forEach((listener) => listener());
}

export function onSessionChange(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
