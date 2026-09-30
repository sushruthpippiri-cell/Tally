import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { login } from "../lib/auth";
import { messageFor } from "../lib/errorMessages";
import { useSession } from "../lib/useSession";

export function LoginPage() {
  const session = useSession();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (session === "signed-in") return <Navigate to="/companies" replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      navigate("/companies", { replace: true });
    } catch (e) {
      setError(e instanceof ApiError ? messageFor(e) : "Sign-in failed. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 p-4">
      <form
        onSubmit={(e) => void submit(e)}
        className="w-full max-w-sm space-y-3 rounded border border-slate-200 bg-white p-6"
      >
        <h1 className="text-xl font-semibold">Sign in</h1>
        <label className="block text-sm">
          Email
          <input
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1 block w-full rounded border border-slate-300 px-2 py-2"
          />
        </label>
        <label className="block text-sm">
          Password
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 block w-full rounded border border-slate-300 px-2 py-2"
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
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
