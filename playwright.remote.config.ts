import { defineConfig } from "@playwright/test";

const baseURL = process.env.RENOTRACE_BASE_URL;
if (!baseURL || new URL(baseURL).protocol !== "https:") {
  throw new Error(
    "Set RENOTRACE_BASE_URL to the public HTTPS frontend origin.",
  );
}

// Deliberately no webServer: this mode can never start local services.
export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: "demo.spec.ts",
  grep: /real FIN-16|FIN-01 credit|two browser contexts|responsive visual/,
  workers: 1,
  timeout: 240_000,
  expect: { timeout: 180_000 },
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL,
    browserName: "chromium",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [360, 768, 1440].map((width) => ({
    name: `public-${width}`,
    use: { viewport: { width, height: 960 } },
  })),
});
