import { test, expect, type Page } from "@playwright/test";
import path from "node:path";
import fs from "node:fs/promises";

test.use({ actionTimeout: 20_000 });

async function includeFacts(page: Page) {
  for (const fact of await page.locator(".guest-fact").all()) {
    await fact.getByLabel("Your decision").selectOption("accept");
    await fact.getByLabel("Belongs to").selectOption("contractor");
  }
}
async function checkComposition(page: Page) {
  await page
    .getByRole("button", { name: "Review invoice composition", exact: true })
    .click();
  for (const line of await page.locator(".invoice-line").all())
    await line.getByLabel("Position review").selectOption("checked");
  await page
    .getByRole("checkbox", {
      name: "I checked the complete invoice composition against the original.",
    })
    .check();
}

test("recheck corrected invoice preserves payment and frozen comparison history", async ({
  page,
}, info) => {
  await page.goto("/review");
  await expect(
    page.getByRole("button", { name: "Delete my review" }),
  ).toBeVisible();
  try {
    await page
      .getByRole("checkbox", { name: /I understand the processing/ })
      .check();
    for (const name of [
      "recheck-estimate.pdf",
      "recheck-payment.pdf",
      "recheck-original.pdf",
    ]) {
      await page
        .getByLabel("Add a document", { exact: true })
        .setInputFiles(path.resolve("fixtures/uploads", name));
      await expect(
        page.getByRole("button", { name: "Save review and calculate" }),
      ).toBeEnabled();
    }
    await includeFacts(page);
    await page
      .getByLabel("Active estimate")
      .selectOption({ label: "Estimate total: USD 6,200.00" });
    await page
      .getByLabel("Current invoice", { exact: true })
      .selectOption({ label: "Amount due: USD 6,200.00" });
    await checkComposition(page);
    await page
      .getByRole("button", { name: "Save review and calculate" })
      .click();
    await expect(page.getByTestId("guest-requested")).toHaveText("$6,200.00");
    await expect(page.getByTestId("guest-remaining")).toHaveText("$5,000.00");
    const card = page.locator('[data-question-code="REQUEST_RECONCILIATION"]');
    await card.locator(":scope > summary").click();
    await card.getByRole("checkbox", { name: /Include this question/ }).check();
    await page
      .getByLabel("Contractor reply (entered by you)")
      .fill(
        "The revised invoice now reflects the earlier $1,200 transfer. Please check the receipt.",
      );
    await page.getByRole("button", { name: "Save reply", exact: true }).click();
    await expect(card.locator(".saved-reply")).toHaveCount(1);
    await page
      .getByRole("combobox", { name: "Previous calculation", exact: true })
      .selectOption({ index: 1 });
    await page
      .getByRole("button", {
        name: "Recheck with new information",
        exact: true,
      })
      .click();
    await expect(page.locator(".recheck-package")).toBeVisible();
    await page.reload();
    await expect(page.locator(".recheck-package")).toBeVisible(); // Draft survives reload.
    await page
      .getByRole("checkbox", { name: /I understand the processing/ })
      .check();
    await page
      .getByLabel("Add a document", { exact: true })
      .setInputFiles(path.resolve("fixtures/uploads/recheck-corrected.pdf"));
    await expect(
      page.getByRole("button", { name: "Save review and calculate" }),
    ).toBeEnabled();
    await expect(
      page.getByRole("button", { name: /View comparison ·/ }),
    ).toHaveCount(0);
    await includeFacts(page);
    await page
      .getByLabel("Current invoice", { exact: true })
      .selectOption({ label: "Amount due: USD 5,000.00" });
    await checkComposition(page);
    await page
      .getByLabel("Existing payment evidence")
      .selectOption({ index: 1 });
    await page
      .getByRole("combobox", { name: "Invoice to compare", exact: true })
      .selectOption({
        label: "recheck-corrected.pdf · Amount due: USD 5,000.00",
      });
    await page
      .getByRole("combobox", { name: "Invoice relationship", exact: true })
      .selectOption("corrected");
    await page.getByRole("checkbox", { name: /Include reply ·/ }).check();
    await page
      .getByLabel("Match previous: Surface preparation")
      .selectOption({ label: "Work · Surface preparation" });
    await page
      .getByRole("checkbox", {
        name: /I confirm added position: Payment reflected/,
      })
      .check();
    await page
      .getByLabel("Evidence for question REQUEST_RECONCILIATION")
      .selectOption({ label: "Earlier bank transfer" });
    await page
      .getByRole("button", { name: "Save recheck package", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Run recheck and save comparison" }),
    ).toBeEnabled();
    // Drop the response after commit. Retrying the identical action must not create another result.
    let lost = false;
    await page.route(
      "**/api/guest/projects/*/rechecks/*/run",
      async (route) => {
        if (!lost) {
          lost = true;
          await route.fetch();
          await route.abort("failed");
        } else await route.continue();
      },
    );
    await page
      .getByRole("button", { name: "Run recheck and save comparison" })
      .click();
    await expect(page.getByRole("alert")).toBeVisible();
    await page
      .getByRole("button", { name: "Run recheck and save comparison" })
      .click();
    await expect(
      page.getByRole("button", { name: /View comparison ·/ }),
    ).toHaveCount(1);
    await expect(page.getByTestId("guest-requested")).toHaveText("$5,000.00");
    await expect(page.getByTestId("guest-remaining")).toHaveText("$5,000.00");
    await page.reload();
    await page.getByRole("button", { name: /View comparison ·/ }).click();
    const comparison = page.getByRole("region", {
      name: "Saved invoice comparison",
    });
    await expect(
      comparison.getByTestId("comparison-requested_now_cents"),
    ).toHaveText("$6,200.00 → $5,000.00");
    await expect(
      comparison.getByTestId("comparison-net_paid_cents"),
    ).toHaveText("$1,200.00 → $1,200.00");
    await expect(
      comparison.getByTestId("comparison-remaining_commitment_cents"),
    ).toHaveText("$5,000.00 → $5,000.00");
    await expect(comparison).toContainText("No additional payment is created.");
    await expect(comparison).toContainText("earlier $1,200 transfer");
    await expect(comparison).toContainText(
      "Preliminary — unresolved evidence remains.",
    );
    await comparison.evaluate((el) =>
      el.scrollIntoView({ block: "start", behavior: "instant" }),
    );
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await fs.mkdir("planning/screenshots/stage8", { recursive: true });
    await page.screenshot({
      path: `planning/screenshots/stage8/comparison-${info.project.name}.png`,
    });
  } finally {
    await page.getByRole("button", { name: "Delete my review" }).click();
    await expect(
      page.getByRole("heading", { name: "Your review has been deleted." }),
    ).toBeVisible();
  }
});
