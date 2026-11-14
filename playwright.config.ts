import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  workers: process.env.CI ? 2 : 3,
  timeout: 30000,
  expect: { timeout: 10000 },
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "http://127.0.0.1:3100",
    browserName: "chromium",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [360, 768, 1440].map((width) => ({
    name: `chromium-${width}`,
    use: { viewport: { width, height: 960 } },
  })),
  webServer: [
    {
      command: "node tools/e2e-api.mjs",
      url: "http://127.0.0.1:8100/healthz",
      reuseExistingServer: false,
      timeout: 60000,
    },
    {
      command:
        "node node_modules/next/dist/bin/next start apps/web --hostname 127.0.0.1 --port 3100",
      url: "http://127.0.0.1:3100",
      reuseExistingServer: false,
      timeout: 60000,
      env: { BACKEND_URL: "http://127.0.0.1:8100" },
    },
  ],
});
