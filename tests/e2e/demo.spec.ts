import { expect, test, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";

const remaining = (page: Page) =>
  page.getByRole("article", { name: "Remaining under recorded terms" });
async function open(page: Page) {
  await page.goto("/");
  await page.getByRole("link", { name: "Try sample", exact: false }).click();
  await expect(remaining(page).locator(".amount")).toHaveText("$4,700");
}
async function choose(page: Page, scenario: string, amount: string) {
  await page.getByRole("button", { name: new RegExp(scenario) }).click();
  await expect(remaining(page).locator(".amount")).toHaveText(amount);
}

test("real FIN-16 decisions, unknown, reset and reload", async ({ page }) => {
  await open(page);
  await choose(page, "FIN-16", "$7,000");
  await expect(remaining(page)).toContainText("Provisional");
  await expect(
    page.getByRole("article", { name: "Requested in this invoice" }),
  ).toContainText("Unknown");
  await page
    .getByRole("radio", { name: "The contractor", exact: true })
    .check();
  await expect(remaining(page).locator(".amount")).toHaveText("$5,000");
  await expect(remaining(page)).not.toContainText("Provisional");
  await page
    .getByRole("radio", { name: "Another recipient", exact: true })
    .check();
  await expect(remaining(page).locator(".amount")).toHaveText("$7,000");
  await expect(remaining(page)).not.toContainText("Provisional");
  await page.getByRole("radio", { name: "I don't know", exact: true }).check();
  await expect(remaining(page)).toContainText("Provisional");
  await page
    .getByRole("radio", { name: "The contractor", exact: true })
    .check();
  await expect(remaining(page).locator(".amount")).toHaveText("$5,000");
  await page.getByRole("button", { name: "Reset sample" }).click();
  await expect(remaining(page).locator(".amount")).toHaveText("$7,000");
  await expect(page.getByRole("radio", { name: "I don't know" })).toBeChecked();
  await expect(remaining(page)).toContainText("Provisional");
  await page.reload();
  await choose(page, "FIN-16", "$7,000");
});

test("FIN-01 credit and FIN-11 increment have real source disclosures", async ({
  page,
}) => {
  await open(page);
  const requested = page.getByRole("article", {
    name: "Requested in this invoice",
  });
  await expect(requested.locator(".amount")).toHaveText("$5,500");
  await remaining(page).locator("summary").click();
  await expect(remaining(page).getByText(/deduct \$800/)).toBeVisible();
  await expect(
    page.getByRole("article", { name: "Current payment conditions" }),
  ).toContainText("Unknown");
  await choose(page, "FIN-11", "$10,500");
  const increment = page
    .locator(".calculation-row")
    .filter({ has: page.getByText("New charge", { exact: true }) });
  await expect(increment.locator("strong").first()).toHaveText("$8,500");
  await increment.locator("summary").click();
  await expect(increment.getByText(/previous \$5,000 valuation/)).toBeVisible();
  await expect(page.locator(".invoice-balances")).toContainText("$2,000");
  await expect(page.locator(".invoice-balances")).toContainText("$8,500");
});

test("two browser contexts do not share decisions", async ({
  page,
  browser,
}) => {
  const other = await browser.newContext();
  const visitor = await other.newPage();
  await open(page);
  await open(visitor);
  await choose(page, "FIN-16", "$7,000");
  await choose(visitor, "FIN-16", "$7,000");
  await page
    .getByRole("radio", { name: "The contractor", exact: true })
    .check();
  await expect(remaining(page).locator(".amount")).toHaveText("$5,000");
  await expect(remaining(visitor).locator(".amount")).toHaveText("$7,000");
  await expect(
    visitor.getByRole("radio", { name: "I don't know" }),
  ).toBeChecked();
  await other.close();
});

test("failed calculation hides old figures and retries the same answer", async ({
  page,
}) => {
  await open(page);
  await choose(page, "FIN-16", "$7,000");
  await page.route("**/api/demo/scenarios/FIN-16/calculate", (route) =>
    route.fulfill({ status: 502, json: { detail: "Unavailable" } }),
  );
  await page
    .getByRole("radio", { name: "The contractor", exact: true })
    .check();
  await expect(page.locator(".error[role=alert]")).toContainText(
    "Calculation unavailable",
  );
  await expect(remaining(page)).toHaveCount(0);
  await page.unroute("**/api/demo/scenarios/FIN-16/calculate");
  await page.getByRole("button", { name: "Retry calculation" }).click();
  await expect(remaining(page).locator(".amount")).toHaveText("$5,000");
});

test("catalog failure and malformed result can be retried", async ({
  page,
}) => {
  await page.route("**/api/demo/scenarios", (route) =>
    route.fulfill({ status: 503, json: {} }),
  );
  await page.route("**/api/demo/scenarios/FIN-01", (route) =>
    route.fulfill({ status: 200, json: { synthetic: false } }),
  );
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Retry sample list" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Retry calculation" }),
  ).toBeVisible();
  await page.unrouteAll();
  await page.getByRole("button", { name: "Retry sample list" }).click();
  await page.getByRole("button", { name: "Retry calculation" }).click();
  await expect(page.getByRole("button", { name: /FIN-16/ })).toBeVisible();
  await expect(remaining(page).locator(".amount")).toHaveText("$4,700");
});

test("late replies cannot replace a newer decision even without transport abort", async ({
  page,
}) => {
  await page.addInitScript(() => {
    const original = window.fetch;
    window.fetch = (input, init) =>
      original(input, { ...init, signal: undefined });
  });
  await open(page);
  await choose(page, "FIN-16", "$7,000");
  let release!: () => void;
  let released!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const delivered = new Promise<void>((resolve) => {
    released = resolve;
  });
  await page.route("**/api/demo/scenarios/FIN-16/calculate", async (route) => {
    const response = await route.fetch();
    if (route.request().postDataJSON().actions[0].answer === "contractor") {
      await gate;
      await route.fulfill({ response });
      released();
    } else await route.fulfill({ response });
  });
  await page
    .getByRole("radio", { name: "The contractor", exact: true })
    .check();
  await expect(page.getByRole("status")).toContainText("Recalculating");
  await expect(remaining(page)).toHaveCount(0);
  await page
    .getByRole("radio", { name: "Another recipient", exact: true })
    .check();
  await expect(remaining(page).locator(".amount")).toHaveText("$7,000");
  release();
  await delivered;
  await expect(
    page.getByRole("radio", { name: "Another recipient" }),
  ).toBeChecked();
  await expect(remaining(page).locator(".amount")).toHaveText("$7,000");
});

test("late scenario response cannot replace the selected scenario", async ({
  page,
}) => {
  await page.addInitScript(() => {
    const original = window.fetch;
    window.fetch = (input, init) =>
      original(input, { ...init, signal: undefined });
  });
  await open(page);
  let release!: () => void;
  let delivered!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const done = new Promise<void>((resolve) => {
    delivered = resolve;
  });
  await page.route("**/api/demo/scenarios/FIN-16", async (route) => {
    const response = await route.fetch();
    await gate;
    await route.fulfill({ response });
    delivered();
  });
  await page.getByRole("button", { name: /FIN-16/ }).click();
  await choose(page, "FIN-11", "$10,500");
  release();
  await done;
  await expect(remaining(page).locator(".amount")).toHaveText("$10,500");
  await expect(page.getByRole("button", { name: /FIN-11/ })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

test("BFF rejects forbidden actions, routes, malformed and oversized bodies", async ({
  request,
}) => {
  expect(
    (
      await request.post("/api/demo/scenarios/FIN-16/calculate", {
        data: { history: {} },
      })
    ).status(),
  ).toBe(422);
  expect(
    (
      await request.post("/api/demo/scenarios/FIN-01/calculate", {
        data: {
          actions: [
            {
              kind: "assign_recipient",
              record_id: "unknown",
              answer: "contractor",
            },
          ],
        },
      })
    ).status(),
  ).toBe(422);
  expect((await request.get("/api/demo/scenarios/FIN-99")).status()).toBe(404);
  expect((await request.get("/api/demo/private/cases")).status()).toBe(404);
  expect(
    (
      await request.post("/api/demo/scenarios/FIN-16/calculate", { data: "{" })
    ).status(),
  ).toBe(400);
  expect(
    (
      await request.post("/api/demo/scenarios/FIN-16/calculate", {
        data: "x".repeat(9000),
      })
    ).status(),
  ).toBe(413);
});

test("keyboard controls and disclosures are accessible", async ({ page }) => {
  await open(page);
  const scenario = page.getByRole("button", { name: /FIN-16/ });
  await scenario.focus();
  await page.keyboard.press("Enter");
  await expect(remaining(page).locator(".amount")).toHaveText("$7,000");
  const recipient = page.getByRole("radio", {
    name: "The contractor",
    exact: true,
  });
  await recipient.focus();
  await page.keyboard.press("Space");
  await expect(remaining(page).locator(".amount")).toHaveText("$5,000");
  const disclosure = remaining(page).locator("summary");
  await disclosure.focus();
  await page.keyboard.press("Enter");
  await expect(
    remaining(page).getByText("Your demo decision", { exact: true }),
  ).toBeVisible();
});

test("responsive visual captures have no horizontal overflow", async ({
  page,
}, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await open(page);
  const directory =
    process.env.RENOTRACE_CAPTURE_DIR ?? info.outputPath("screenshots");
  await mkdir(directory, { recursive: true });
  for (const [scenario, amount] of [
    ["FIN-01", "$4,700"],
    ["FIN-16", "$7,000"],
    ["FIN-11", "$10,500"],
  ]) {
    await choose(page, scenario, amount);
    await expect(page.locator(".synthetic-badge")).toBeInViewport();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({
      path: path.join(directory, `${scenario}-${info.project.name}.png`),
      fullPage: true,
      animations: "disabled",
    });
  }
  expect(errors).toEqual([]);
});
