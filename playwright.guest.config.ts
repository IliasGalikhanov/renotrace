import { defineConfig } from "@playwright/test";

const remote = process.env.RENOTRACE_BASE_URL;
export default defineConfig({
  testDir: "./tests/guest",
  workers: 1,
  fullyParallel: false,
  timeout: 240_000,
  expect: { timeout: 120_000 },
  reporter: "list",
  use: {
    baseURL: remote || "http://127.0.0.1:3106",
    browserName: "chromium",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [360, 768, 1440].map((width) => ({
    name: `guest-${width}`,
    use: { viewport: { width, height: 960 } },
  })),
  webServer: remote
    ? undefined
    : {
        command:
          "node node_modules/next/dist/bin/next start apps/web --hostname 127.0.0.1 --port 3106",
        url: "http://127.0.0.1:3106",
        timeout: 60_000,
        reuseExistingServer: false,
        env: { BACKEND_URL: "http://127.0.0.1:8106" },
      },
});
