import { defineConfig, devices } from "@playwright/test";

// Both projects run in a browser time zone far from the company's (TZ-1.1, D-051 #6).
const timezoneId = "America/Los_Angeles";

export default defineConfig({
  testDir: "e2e",
  outputDir: "../logs/e2e",
  reporter: [["list"], ["html", { outputFolder: "../logs/e2e-report", open: "never" }]],
  use: {
    baseURL: "http://localhost:4173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    timezoneId,
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], timezoneId } },
    {
      name: "mobile", // NFR-UI-1: 360 px, touch
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 360, height: 740 },
        isMobile: true,
        hasTouch: true,
        timezoneId,
      },
    },
  ],
  webServer: process.env.LIVE
    ? undefined
    : {
        command: "npm run build && npm run preview -- --port 4173 --strictPort",
        port: 4173,
        reuseExistingServer: !process.env.CI,
      },
});
