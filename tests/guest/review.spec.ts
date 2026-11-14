import { test, expect } from "@playwright/test";
import path from "node:path";
import fs from "node:fs/promises";

test("own documents, real calculation, private session, reload and deletion", async ({
  page,
  browser,
}, testInfo) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Review my invoice" }).click();
  await expect(
    page.getByRole("button", { name: "Delete my review" }),
  ).toBeVisible();
  await page
    .getByRole("checkbox", { name: /I understand the processing/ })
    .check();
  for (const name of [
    "invoice.pdf",
    "estimate.pdf",
    "payment.pdf",
    "payment.pdf",
  ]) {
    await page
      .getByLabel("Add a document", { exact: true })
      .setInputFiles(path.resolve("fixtures/uploads", name));
    await expect(
      page.getByLabel("Add a document", { exact: true }),
    ).toBeEnabled();
    await expect(
      page.getByRole("button", { name: "Save review and calculate" }),
    ).toBeEnabled();
  }
  await expect(page.locator(".guest-document")).toHaveCount(3);
  const facts = page.locator(".guest-fact");
  await expect(facts).toHaveCount(4);
  for (const fact of await facts.all()) {
    await fact.getByLabel("Belongs to").selectOption("contractor");
    await fact.getByLabel("Your decision").selectOption("accept");
  }
  await page
    .getByLabel("Active estimate")
    .selectOption({ label: "Estimate total: USD 10,000.00" });
  await page
    .getByLabel("Current invoice", { exact: true })
    .selectOption({ label: "Amount due: USD 7,000.00" });
  await page.getByRole("button", { name: "Save review and calculate" }).click();
  await expect(page.getByTestId("guest-remaining")).toHaveText("$7,000.00");
  await expect(page.getByTestId("guest-requested")).toHaveText("$7,000.00");
  await expect(
    page.getByRole("region", { name: "Your calculation" }),
  ).toContainText("Payment terms: after written approval");
  const cookie = (await page.context().cookies()).find(
    (c) => c.name === "__Host-renotrace",
  );
  expect(cookie?.httpOnly).toBe(true);
  expect(cookie?.secure).toBe(true);
  expect(await page.evaluate(() => document.cookie)).not.toContain("renotrace");

  await page.reload();
  await expect(page.getByTestId("guest-remaining")).toHaveText("$7,000.00");
  const second = await browser.newContext();
  const other = await second.newPage();
  await other.goto(new URL("/review", page.url()).toString());
  await expect(
    other.getByRole("button", { name: "Delete my review" }),
  ).toBeVisible();
  await expect(other.locator(".guest-document")).toHaveCount(0);
  await other.getByRole("button", { name: "Delete my review" }).click();
  await second.close();

  const payment = facts.filter({ hasText: "Total: USD 3,000.00" });
  await payment.getByLabel("Belongs to").selectOption("other");
  await expect(page.getByTestId("guest-remaining")).toHaveCount(0);
  await page.getByRole("button", { name: "Save review and calculate" }).click();
  await expect(page.getByTestId("guest-remaining")).toHaveText("$10,000.00");
  await payment.getByLabel("Belongs to").selectOption("contractor");
  await page.getByRole("button", { name: "Save review and calculate" }).click();
  await expect(page.getByTestId("guest-remaining")).toHaveText("$7,000.00");
  await page
    .getByRole("button", { name: "View estimate.pdf", exact: true })
    .click();
  await expect(page.getByTitle("Original document preview")).toBeVisible();
  await page.getByRole("button", { name: "Close original" }).click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await fs.mkdir("planning/screenshots/stage6", { recursive: true });
  await page
    .getByRole("region", { name: "Your calculation" })
    .scrollIntoViewIfNeeded();
  await page.screenshot({
    path: `planning/screenshots/stage6/guest-result-${testInfo.project.name}.png`,
  });
  await page.getByRole("button", { name: "Delete my review" }).click();
  await expect(
    page.getByRole("heading", { name: "Your review has been deleted." }),
  ).toBeVisible();
});

test("guest BFF rejects cross-origin mutations and arbitrary routes", async ({
  request,
  baseURL,
}) => {
  expect(
    (
      await request.post("/api/guest/session", {
        headers: { Origin: "https://unrelated.invalid" },
      })
    ).status(),
  ).toBe(403);
  expect(
    (
      await request.post("/api/guest/maintenance/cleanup", {
        headers: { Origin: baseURL! },
      })
    ).status(),
  ).toBe(404);
  expect(
    (
      await request.get(
        "/api/guest/projects/00000000-0000-0000-0000-000000000000",
      )
    ).status(),
  ).toBe(404);
});
