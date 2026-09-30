import { defineConfig, devices } from "@playwright/test";

/** Local only: sign in, reload and sign out against a real backend (`make up`, or any backend
 * at BACKEND_URL) with a real user (LIVE_EMAIL, LIVE_PASSWORD). Chrome over http; WebKit,
 * Safari's engine, over HTTPS: Safari does not send a Secure cookie back over plain
 * http://localhost, so there the session only survives a reload over HTTPS (D-051 #8).
 * Needs `make dev-tls HOST=127.0.0.1` once for the certificate. */
const timezoneId = "America/Los_Angeles";

export default defineConfig({
  testDir: "e2e",
  testMatch: "live.spec.ts",
  outputDir: "../logs/e2e-live",
  use: { trace: "retain-on-failure", timezoneId },
  projects: [
    {
      name: "chrome-http",
      use: { ...devices["Desktop Chrome"], baseURL: "http://localhost:5173", timezoneId },
    },
    {
      name: "safari-https",
      use: {
        ...devices["Desktop Safari"],
        baseURL: "https://localhost:5174",
        ignoreHTTPSErrors: true, // the throwaway dev CA
        timezoneId,
      },
    },
  ],
  webServer: [
    {
      command: "npm run dev -- --port 5173 --strictPort",
      url: "http://localhost:5173/login",
      reuseExistingServer: true,
    },
    {
      command: "npm run dev:https -- --port 5174 --strictPort",
      url: "https://localhost:5174/login",
      ignoreHTTPSErrors: true,
      reuseExistingServer: true,
    },
  ],
});
