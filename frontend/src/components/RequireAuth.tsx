import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useSession } from "../lib/useSession";
import { Loading } from "./ui";

export const CHANGE_PASSWORD = "/account/password";

/** Pages behind sign-in. While a page load restores the session from the cookie, it waits. An
 * initial password reaches only the change-password page (D-052; the API enforces it too). */
export function RequireAuth({ children }: { children: ReactNode }) {
  const session = useSession();
  const location = useLocation();
  if (session === "restoring") return <Loading label="Restoring your session" />;
  if (session === "signed-out") return <Navigate to="/login" replace state={{ from: location }} />;
  if (session === "must-change-password" && location.pathname !== CHANGE_PASSWORD) {
    return <Navigate to={CHANGE_PASSWORD} replace />;
  }
  return <>{children}</>;
}
