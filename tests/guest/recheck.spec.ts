import { test, expect, type Page } from "@playwright/test";
import path from "node:path";
import fs from "node:fs/promises";
import { spawnSync } from "node:child_process";

async function downloadPdf(page: Page, name: string, output: string) {
  const downloaded = page.waitForEvent("download", { timeout: 120_000 });
  await page.getByRole("button", { name, exact: true }).click();
  const file = await downloaded;
  expect(file.suggestedFilename()).toMatch(
    /^renotrace-(snapshot|comparison)-[a-f0-9-]+\.pdf$/,
  );
  await file.saveAs(output);
  const python = path.resolve(
    process.platform === "win32"
      ? ".venv/Scripts/python.exe"
      : ".venv/bin/python",
  );
  const inspected = spawnSync(python, ["tools/inspect_guest_pdf.py", output], {
    encoding: "utf8",
  });
  expect(inspected.status, inspected.stderr).toBe(0);
  const report = JSON.parse(inspected.stdout) as {
    pages: number;
    text: string;
  };
  expect(report.pages).toBeGreaterThan(1);
  expect(report.text).toContain("FICTIONAL EXAMPLE");
  expect(report.text).toContain("Source register");
  expect(report.text).toContain("PRELIMINARY");
  return report.text.replace(/PDF generated: .*? UTC/, "PDF generated: [time]");
}

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

test("recheck corrected invoice preserves payment and frozen comparison history with PDF downloads", async ({
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
      "recheck-original.pdf",
      "recheck-estimate.pdf",
      "recheck-payment.pdf",
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
    await page
      .getByRole("button", { name: /View calculation · revision/ })
      .first()
      .click();
    await expect(
      page.getByText(/Your downloaded copy remains on your device/),
    ).toBeVisible();
    await page.route(
      "**/api/guest/projects/*/exports",
      async (route) => {
        await route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({
            detail: "Temporary export failure for retry check",
          }),
        });
      },
      { times: 1 },
    );
    await page
      .getByRole("button", { name: "Download calculation PDF", exact: true })
      .click();
    await expect(
      page
        .getByRole("region", { name: "Download selected saved report" })
        .getByRole("alert"),
    ).toContainText("Temporary export failure");
    const initialPdf = await downloadPdf(
      page,
      "Download calculation PDF",
      info.outputPath("initial.pdf"),
    );
    expect(initialPdf).toContain("$6,200.00");
    expect(initialPdf).toContain("ACTIVE in this selected calculation");
    // Fast extraction may finish before a polling read records a processing card.
    // The deterministic processing transition is covered by the domain regression.
    expect(initialPdf).toContain(
      "Historical messages are not current document status",
    );
    expect(initialPdf).not.toContain("earlier $1,200 transfer");
    await page
      .getByRole("button", { name: "Close historical snapshot" })
      .click();
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
    await expect(page.locator('.guest-error[role="alert"]')).toBeVisible();
    await page
      .getByRole("button", { name: "Run recheck and save comparison" })
      .click();
    await expect(
      page.getByRole("button", { name: /View comparison ·/ }),
    ).toHaveCount(1);
    await expect(page.getByTestId("guest-requested")).toHaveText("$5,000.00");
    await expect(page.getByTestId("guest-remaining")).toHaveText("$5,000.00");
    await page.reload();
    await page.route(
      "**/api/guest/projects/*/comparisons/*",
      (route) =>
        route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({
            detail: "Saved comparison temporarily unavailable",
          }),
        }),
      { times: 1 },
    );
    await page.getByRole("button", { name: /View comparison ·/ }).click();
    await expect(
      page.getByRole("button", { name: "Retry saved evidence" }),
    ).toBeVisible();
    await expect(
      page.getByRole("region", { name: "Saved invoice comparison" }),
    ).toHaveCount(0);
    await page.getByRole("button", { name: "Retry saved evidence" }).click();
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
    const comparedPdf = await downloadPdf(
      page,
      "Download recheck PDF",
      info.outputPath("comparison.pdf"),
    );
    expect(comparedPdf).toContain("$6,200.00");
    expect(comparedPdf).toContain("$5,000.00");
    expect(comparedPdf).toContain("-$1,200.00");
    expect(comparedPdf).toContain("No additional payment is created.");
    expect(comparedPdf).toContain("earlier $1,200 transfer");
    expect(comparedPdf).toContain(
      "HISTORICAL - absent from this selected calculation",
    );
    expect(comparedPdf).toContain("Previous conclusion requires reassessment");
    expect(comparedPdf).not.toContain("New question:");
    await expect(
      comparison.locator('[data-question-presence="historical"]').first(),
    ).toBeVisible();
    await expect(
      comparison.getByRole("heading", {
        name: "Questions first recorded since the previous snapshot",
      }),
    ).toBeVisible();
    // Re-export the old selection after the new reply, documents and calculation.
    await page
      .getByRole("button", { name: /View calculation · revision/ })
      .last()
      .click();
    const historicalPdf = await downloadPdf(
      page,
      "Download calculation PDF",
      info.outputPath("historical.pdf"),
    );
    expect(historicalPdf).toBe(initialPdf);
    await page
      .getByRole("button", { name: "Close historical snapshot" })
      .click();
    await comparison.evaluate((el) =>
      el.scrollIntoView({ block: "start", behavior: "instant" }),
    );
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await fs.mkdir("planning/screenshots/stage10", { recursive: true });
    await page.screenshot({
      path: `planning/screenshots/stage10/pdf-download-${info.project.name}.png`,
    });
    await comparison
      .locator('[data-question-presence="historical"]')
      .first()
      .scrollIntoViewIfNeeded();
    await page.screenshot({
      path: `planning/screenshots/stage10/question-history-${info.project.name}.png`,
    });
    if (process.env.RENOTRACE_BASE_URL && info.project.name === "guest-1440") {
      await fs.mkdir("output/pdf", { recursive: true });
      await fs.copyFile(
        info.outputPath("comparison.pdf"),
        "output/pdf/renotrace-stage10-public-recheck.pdf",
      );
    }
  } finally {
    await page.getByRole("button", { name: "Delete my review" }).click();
    await expect(
      page.getByRole("heading", { name: "Your review has been deleted." }),
    ).toBeVisible();
  }
});
