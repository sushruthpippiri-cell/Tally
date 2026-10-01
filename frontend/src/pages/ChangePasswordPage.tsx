import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { changePassword } from "../lib/auth";
import { messageFor } from "../lib/errorMessages";
import { useSession } from "../lib/useSession";
import { SignOut } from "./SignOut";

const input = "mt-1 block w-full rounded border border-slate-300 px-2 py-2";

/** Every role's own password (SEC-1.1). After an Owner created the account, the first sign-in
 * lands here and nothing else opens until it is done (D-052). */
export function ChangePasswordPage() {
  const required = useSession() === "must-change-password";
  const navigate = useNavigate();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (next !== repeat) return setError("The two new passwords are not the same.");
    if (next === current) return setError("Choose a password different from the current one.");
    setBusy(true);
    try {
      await changePassword(current, next);
      if (required) navigate("/companies", { replace: true });
      else setDone(true);
    } catch (e) {
      setError(e instanceof ApiError ? messageFor(e) : "The password could not be changed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-sm space-y-4 p-4">
      <h1 className="text-xl font-semibold">
        {required ? "Choose your password" : "Change password"}
      </h1>
      {required && (
        <p role="note" className="rounded border border-amber-300 bg-amber-50 p-3 text-sm">
          Your account was created with a password someone else chose. Choose your own before you
          continue; the one you were given stops working.
        </p>
      )}
      {done ? (
        <p role="status" className="text-green-800">
          Password changed. You are still signed in here; other devices are signed out.
        </p>
      ) : (
        <form onSubmit={(e) => void submit(e)} className="space-y-3">
          <label className="block text-sm">
            {required ? "Password you were given" : "Current password"}
            <input
              type="password"
              autoComplete="current-password"
              required
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              className={input}
            />
          </label>
          <label className="block text-sm">
            New password (at least 8 characters)
            <input
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              value={next}
              onChange={(e) => setNext(e.target.value)}
              className={input}
            />
          </label>
          <label className="block text-sm">
            New password again
            <input
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              value={repeat}
              onChange={(e) => setRepeat(e.target.value)}
              className={input}
            />
          </label>
          {error && (
            <p role="alert" className="text-sm text-red-800">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={busy}
            className="w-full rounded bg-slate-800 px-3 py-2 text-white disabled:opacity-50"
          >
            {busy ? "Saving…" : "Save password"}
          </button>
        </form>
      )}
      <div className="flex items-center justify-between gap-2 text-sm">
        {required ? (
          <span />
        ) : (
          <Link to="/companies" className="underline">
            Back to your companies
          </Link>
        )}
        <SignOut />
      </div>
    </main>
  );
}
