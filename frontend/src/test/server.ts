import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll } from "vitest";

/** One MSW server per test file: `withMockApi()` at the top, then `server.use(...)` per test. */
export const server = setupServer();

export function withMockApi(): void {
  beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
  afterEach(() => server.resetHandlers());
  afterAll(() => server.close());
}
