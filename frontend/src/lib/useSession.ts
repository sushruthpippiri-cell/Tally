import { useEffect, useState, useSyncExternalStore } from "react";
import { refresh } from "./auth";
import { getAccessToken, onSessionChange } from "./session";

export type SessionState = "restoring" | "signed-in" | "signed-out";

let restore: Promise<boolean> | null = null;

/** Signed in or not. On first use after a page load, one refresh restores the session from the
 * HttpOnly cookie (D-051 #1). */
export function useSession(): SessionState {
  const token = useSyncExternalStore(onSessionChange, getAccessToken);
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
  if (token !== null) return "signed-in";
  return restored ? "signed-out" : "restoring";
}

/** Tests only: forget the page-load restore. */
export function resetRestore(): void {
  restore = null;
}
