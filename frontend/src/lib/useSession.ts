import { useEffect, useState, useSyncExternalStore } from "react";
import { refresh } from "./auth";
import { getAccessToken, getMustChangePassword, onSessionChange } from "./session";

export type SessionState = "restoring" | "signed-in" | "must-change-password" | "signed-out";

let restore: Promise<boolean> | null = null;

/** Signed in or not. On first use after a page load, one refresh restores the session from the
 * HttpOnly cookie (D-051 #1). */
export function useSession(): SessionState {
  const token = useSyncExternalStore(onSessionChange, getAccessToken);
  const mustChange = useSyncExternalStore(onSessionChange, getMustChangePassword);
  const [restored, setRestored] = useState(token !== null);
  useEffect(() => {
    if (restored) return;
    restore ??= refresh();
    let live = true;
    void restore.then(() => {
      if (live) setRestored(true);
    });
    return () => {
      live = false;
    };
  }, [restored]);
  if (token !== null) return mustChange ? "must-change-password" : "signed-in";
  return restored ? "signed-out" : "restoring";
}

/** Tests only: forget the page-load restore. */
export function resetRestore(): void {
  restore = null;
}
