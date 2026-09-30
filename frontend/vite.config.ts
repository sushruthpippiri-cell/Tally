/// <reference types="vitest/config" />
import { readFileSync } from "node:fs";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig, type ProxyOptions } from "vite";
import { SECURITY_HEADERS } from "./security/csp.ts";

// The app calls /api/* on its own origin; the backend has no /api prefix (D-051 #4).
const backend = process.env.BACKEND_URL ?? "http://localhost:8000";
const api: Record<string, ProxyOptions> = {
  "/api": { target: backend, changeOrigin: true, rewrite: (path) => path.replace(/^\/api/, "") },
};

export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: api,
    // Safari keeps a Secure cookie only over HTTPS (D-051 #8): `make dev-tls`, then dev:https.
    https:
      mode === "https"
        ? {
            cert: readFileSync("../dev-https/server.pem"),
            key: readFileSync("../dev-https/server-key.pem"),
          }
        : undefined,
  },
  preview: { proxy: api, headers: SECURITY_HEADERS },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}", "security/**/*.test.ts"],
    env: { TZ: "America/Los_Angeles" }, // a browser far from the company's time zone
  },
}));
