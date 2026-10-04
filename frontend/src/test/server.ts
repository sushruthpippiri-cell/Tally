import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll } from "vitest";

/** Every company page asks whether Payment Behaviour may be listed (FR-PAY-6): by default it
 * may not, as while gate G25 has not passed. A test overrides it with `server.use`. */
const DEFAULTS = [
  http.get("*/api/companies/:companyId/analytics/payment-behaviour", () =>
    HttpResponse.json({
      available: false,
      reason: "Awaiting Tally validation (G25)",
      unverified_gates: ["G25"],
    }),
  ),
  // the filter pickers' choices: none unless a test serves some
  http.get("*/api/companies/:companyId/masters/options", () => HttpResponse.json([])),
];

/** One MSW server per test file: `withMockApi()` at the top, then `server.use(...)` per test. */
export const server = setupServer(...DEFAULTS);

export function withMockApi(): void {
  beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
  afterEach(() => server.resetHandlers());
  afterAll(() => server.close());
}
