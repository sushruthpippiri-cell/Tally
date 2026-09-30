import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useSession } from "../lib/useSession";
import { Loading } from "./ui";

/** Pages behind sign-in. While a page load restores the session from the cookie, it waits. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const session = useSession();
  const location = useLocation();
  if (session === "restoring") return <Loading label="Restoring your session" />;
  if (session === "signed-out") return <Navigate to="/login" replace state={{ from: location }} />;
  return <>{children}</>;
}
