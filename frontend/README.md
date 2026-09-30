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
