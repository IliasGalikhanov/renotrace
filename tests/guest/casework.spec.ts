import { test, expect } from "@playwright/test";
import path from "node:path";
import fs from "node:fs/promises";

test.use({ actionTimeout: 20_000 });

test("persistent question, text reply, decisions, frozen calculations and reload", async ({
  page,
}, testInfo) => {
  await page.goto("/review");
  await expect(
    page.getByRole("button", { name: "Delete my review" }),
  ).toBeVisible();
  try {
    await page
      .getByRole("checkbox", { name: /I understand the processing/ })
      .check();
    for (const name of ["estimate.pdf", "payment.pdf", "invoice.pdf"]) {
      await page
        .getByLabel("Add a document", { exact: true })
        .setInputFiles(path.resolve("fixtures/uploads", name));
      await expect(
        page.getByRole("button", { name: "Save review and calculate" }),
      ).toBeEnabled();
    }
    for (const fact of await page.locator(".guest-fact").all()) {
      await fact.getByLabel("Your decision").selectOption("accept");
      // Keep the payment recipient unknown: a real normalization question.
      if (!(await fact.textContent())?.includes("Total: USD 3,000.00"))
        await fact.getByLabel("Belongs to").selectOption("contractor");
    }
    await page
      .getByLabel("Active estimate")
      .selectOption({ label: "Estimate total: USD 10,000.00" });
    await page
      .getByLabel("Current invoice", { exact: true })
      .selectOption({ label: "Amount due: USD 7,000.00" });
    await page
      .getByRole("button", { name: "Save review and calculate" })
      .click();
    await expect(page.getByTestId("guest-remaining")).toHaveText("$10,000.00");
    const card = page.locator('[data-question-code="UNRESOLVED_RECIPIENT"]');
    await expect(card).toHaveCount(1);
    await card.locator(":scope > summary").click();
    await expect(card.locator(".contractor-question")).toContainText(
      "USD 3,000.00",
    );
    await card
      .getByRole("button", { name: "Copy question", exact: true })
      .click();
    await expect(
      page
        .getByRole("status")
        .filter({ hasText: /Question copied|Copy is unavailable/ }),
    ).toBeVisible();
    await card.getByRole("checkbox", { name: /Include this question/ }).check();
    await page
      .getByLabel("Contractor reply (entered by you)")
      .fill(
        "This may cover part of the work. I cannot confirm who received it.",
      );
    // Simulate a response lost after the backend committed. Same-key retry must not duplicate.
    let lost = false;
    await page.route("**/api/guest/projects/*/replies", async (route) => {
      if (!lost) {
        lost = true;
        await route.fetch();
        await route.abort("failed");
      } else await route.continue();
    });
    await page.getByRole("button", { name: "Save reply", exact: true }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await page.getByRole("button", { name: "Save reply", exact: true }).click();
    await expect(card.locator(".saved-reply")).toHaveCount(1);
    await expect(page.getByTestId("guest-remaining")).toHaveText("$10,000.00");
    await expect(card).toContainText("Awaiting explanation");
    await card
      .getByRole("combobox", { name: "Evidence assessment", exact: true })
      .selectOption("answer_insufficient");
    await card
      .getByRole("combobox", { name: "Owner decision", exact: true })
      .selectOption("accept_explanation");
    await card
      .getByLabel("Reason for this assessment or decision")
      .fill(
        "I accept the explanation, but the recipient still lacks evidence.",
      );
    await card
      .getByRole("button", { name: "Save assessment / decision" })
      .click();
    await expect(card).toContainText("Answer received — evidence insufficient");
    await expect(page.getByTestId("unresolved-history")).toContainText(
      "1 unresolved question",
    );
    await page.reload();
    await expect(card).toHaveCount(1);
    await card.locator(":scope > summary").click();
    await expect(card.locator(".reply-text").first()).toContainText(
      "cannot confirm",
    );
    await expect(card).toContainText("Accept explanation");
    await card.getByRole("button", { name: "Edit reply", exact: true }).click();
    await page
      .getByLabel("Contractor reply (entered by you)")
      .fill(
        "Correction: the recipient remains uncertain. No new invoice is available.",
      );
    await page.getByRole("button", { name: "Save reply version" }).click();
    await expect(card.locator(".saved-reply")).toContainText("version 2");
    await card
      .getByRole("combobox", { name: "Owner decision", exact: true })
      .selectOption("stop_unresolved");
    await card
      .getByLabel("Reason for this assessment or decision")
      .fill("Stopping for now with evidence unresolved.");
    await card
      .getByRole("button", { name: "Save assessment / decision" })
      .click();
    await expect(card).toContainText("Stop clarifying — unresolved");
    const payment = page
      .locator(".guest-fact")
      .filter({ hasText: "Total: USD 3,000.00" });
    await payment.getByLabel("Belongs to").selectOption("contractor");
    await page
      .getByRole("button", { name: "Save review and calculate" })
      .click();
    await expect(page.getByTestId("guest-remaining")).toHaveText("$7,000.00");
    await expect(card.locator(":scope > summary")).toContainText(
      "Needs recheck",
    );
    await expect(card.locator(".saved-reply")).toHaveCount(1);
    await expect(card).toContainText("Stop clarifying — unresolved");
    await page
      .getByRole("button", { name: /View calculation · revision/ })
      .last()
      .click();
    await expect(page.getByTestId("snapshot-remaining")).toHaveText(
      "$10,000.00",
    );
    await expect(
      page.getByRole("region", { name: "Historical calculation" }),
    ).toContainText("Historical snapshot — read only");
    await fs.mkdir("planning/screenshots/stage7", { recursive: true });
    await page
      .getByRole("region", { name: "Historical calculation" })
      .evaluate((el) => el.scrollIntoView({ block: "start" }));
    await page.screenshot({
      path: `planning/screenshots/stage7/snapshot-${testInfo.project.name}.png`,
    });
    await page
      .getByRole("button", { name: "Close historical snapshot" })
      .click();
    await expect(page.getByTestId("guest-remaining")).toHaveText("$7,000.00");
    await card.locator(":scope > summary").scrollIntoViewIfNeeded();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await fs.mkdir("planning/screenshots/stage7", { recursive: true });
    await page.screenshot({
      path: `planning/screenshots/stage7/history-${testInfo.project.name}.png`,
    });
  } finally {
    await page.getByRole("button", { name: "Delete my review" }).click();
    await expect(
      page.getByRole("heading", { name: "Your review has been deleted." }),
    ).toBeVisible();
  }
});
