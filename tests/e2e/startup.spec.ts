import { expect, test } from "@playwright/test";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { createServer } from "node:http";

test("real BFF tolerates a backend that wakes after 55 seconds", async ({
  page,
}, info) => {
  test.skip(
    info.project.name !== "chromium-1440",
    "One real startup is sufficient; retry UI is checked at every width.",
  );
  test.setTimeout(90_000);
  let readyAt = Number.POSITIVE_INFINITY;
  const proxy = createServer((request, response) => {
    const timer = setTimeout(
      async () => {
        if (response.destroyed) return;
        try {
          const upstream = await fetch(`http://127.0.0.1:8100${request.url}`);
          response.writeHead(upstream.status, {
            "Content-Type": "application/json",
          });
          response.end(await upstream.text());
        } catch {
          response.writeHead(503).end();
        }
      },
      Math.max(0, readyAt - Date.now()),
    );
    response.on("close", () => clearTimeout(timer));
  });
  proxy.listen(0, "127.0.0.1");
  await once(proxy, "listening");
  const address = proxy.address();
  if (!address || typeof address === "string")
    throw new Error("Missing test port");
  const web = spawn(
    process.execPath,
    [
      "node_modules/next/dist/bin/next",
      "start",
      "apps/web",
      "--hostname",
      "127.0.0.1",
      "--port",
      "3110",
    ],
    {
      env: { ...process.env, BACKEND_URL: `http://127.0.0.1:${address.port}` },
      stdio: "ignore",
      windowsHide: true,
    },
  );
  try {
    await expect
      .poll(
        async () => {
          if (web.exitCode !== null)
            throw new Error("Test frontend exited early");
          try {
            return (await fetch("http://127.0.0.1:3110")).status;
          } catch {
            return 0;
          }
        },
        { timeout: 15_000 },
      )
      .toBe(200);
    readyAt = Date.now() + 55_000;
    await page.goto("http://127.0.0.1:3110");
    const remaining = page.getByRole("article", {
      name: "Remaining under recorded terms",
    });
    await expect(page.getByRole("status")).toContainText(
      "may need up to 3 minutes",
    );
    await expect(remaining).toHaveCount(0);
    await expect(page.getByRole("status")).toContainText("Attempt 2 of 4", {
      timeout: 30_000,
    });
    await expect(remaining).toHaveCount(0);
    await expect(remaining.locator(".amount")).toHaveText("$4,700", {
      timeout: 40_000,
    });
    await expect(page.getByRole("button", { name: /FIN-16/ })).toBeVisible();
    await expect(page.locator(".error[role=alert]")).toHaveCount(0);
  } finally {
    web.kill();
    proxy.closeAllConnections();
    await new Promise<void>((resolve) => proxy.close(() => resolve()));
  }
});
