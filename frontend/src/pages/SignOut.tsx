import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { logout } from "../lib/auth";

export function SignOut() {
  const navigate = useNavigate();
  const queries = useQueryClient();
  return (
    <button
      type="button"
      className="rounded border border-slate-300 px-3 py-1"
      onClick={() =>
        void logout().then(() => {
          queries.clear(); // nothing of the last user's data stays in memory
          navigate("/login", { replace: true });
        })
      }
    >
      Sign out
    </button>
  );
}
