# Frontend

React + TypeScript (strict) + Tailwind + React Router + TanStack Query (D-018). API types are
generated from the backend's OpenAPI, never hand-written.

| Command                              | Does                                                                                                                                                              |
| ------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `npm run dev`                        | Dev server on http://localhost:5173; `/api/*` is proxied to the backend (`BACKEND_URL`, default http://localhost:8000) with the `/api` prefix stripped (D-051 #4) |
| `npm run dev:https`                  | The same over HTTPS with the P7 dev certificate (`make dev-tls` first); needed for Safari (below)                                                                 |
| `npm test`                           | Vitest (jsdom, browser time zone America/Los_Angeles)                                                                                                             |
| `npm run e2e`                        | Playwright, desktop and 360 px mobile projects, against `vite preview` with the production CSP                                                                    |
| `npm run lint` / `npm run typecheck` | ESLint + Prettier / `tsc`                                                                                                                                         |
| `npm run gen:api`                    | After an API change: first `uv run python -m tally_tools.openapi` (repo root), then this                                                                          |

Money stays a decimal string from the API to the screen and is never added up in the browser;
dates are shown in the company's time zone (D-051 #5, #6).

## Checking sign-in by hand (Chrome and Safari)

Safari does not send a `Secure` cookie back over plain `http://localhost`, so there a reload
loses the session. Check both browsers over HTTPS with the P7 dev certificate (D-051 #8):

1. Once: `make dev-tls HOST=127.0.0.1` (repo root) creates `dev-https/` (a throwaway CA and a
   certificate for localhost). Trust the CA for the check: open `dev-https/ca.pem` in Keychain
   Access, add it to the **login** keychain, open it, and set **Trust → When using this
   certificate: Always Trust**. Delete it from Keychain Access when you are done.
2. `make up` (the backend on :8000), and create a user if you have none:
   `cd backend && uv run python -m app.cli create-owner --email you@example.com --name You`.
3. `npm run dev:https`, then open **https://localhost:5173** in Chrome and in Safari.
4. In each: sign in; reload (you stay signed in); sign out; reload (you are at Sign in).
   In the developer tools, Storage shows nothing in Local or Session Storage, and the
   `tally_refresh` cookie is HttpOnly, Secure and SameSite=Strict with path `/api/auth`.

`npm run e2e:live` runs the same steps automatically in Chrome (http) and WebKit, Safari's
engine (https), against the backend at `BACKEND_URL` (default http://localhost:8000):
`LIVE_EMAIL=you@example.com LIVE_PASSWORD=… npm run e2e:live`.

A reverse proxy in front of the backend must keep the browser's `Host` header (Vite's does):
the refresh and logout endpoints compare the request's `Origin` with it (CSRF, D-051 #2).
