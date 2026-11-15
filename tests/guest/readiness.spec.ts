import { test, expect } from "@playwright/test";
import path from "node:path";
import fs from "node:fs/promises";
import { spawnSync } from "node:child_process";

test.use({ actionTimeout: 20_000 });

test("ordinary invoice: correct candidate meaning and add missed source-linked positions", async ({
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
      "showcase-ordinary-invoice.pdf",
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
    for (const fact of await page.locator(".guest-fact").all()) {
      const snippet = await fact.locator("blockquote").innerText();
      if (/Wall painting|Floor protection|Skirting board/.test(snippet)) {
        await fact.getByLabel("Meaning").selectOption("unknown");
        await fact.getByLabel("Your decision").selectOption("reject");
      } else {
        await fact.getByLabel("Your decision").selectOption("accept");
        await fact.getByLabel("Belongs to").selectOption("contractor");
      }
    }
    await page
      .getByLabel("Active estimate")
      .selectOption({ label: "Estimate total: USD 6,200.00" });
    await page
      .getByLabel("Current invoice", { exact: true })
      .selectOption({ label: "Amount due: USD 6,200.00" });
    await expect(
      page.getByText(/No invoice positions were recognised/),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Review invoice composition", exact: true })
      .click();
    await expect(page.locator(".invoice-line")).toHaveCount(0);
    for (const [description, amount] of [
      ["Wall painting", "3800.00"],
      ["Floor protection", "400.00"],
      ["Skirting board installation", "2000.00"],
    ]) {
      await page
        .getByRole("button", { name: "Add missed position", exact: true })
        .click();
      const line = page.locator(".invoice-line").last();
      await line.getByLabel("Position meaning").selectOption("work");
      await line.getByLabel("Description", { exact: true }).fill(description);
      await line.getByLabel("Position amount (USD)").fill(amount);
      await line.getByLabel("Source page").selectOption("1");
      await line.getByRole("button", { name: "View position source" }).click();
      await expect(page.getByTitle("Original document preview")).toBeVisible();
      await page.getByRole("button", { name: "Close original" }).click();
      await line.getByLabel("Position review").selectOption("checked");
    }
    await page
      .getByRole("checkbox", {
        name: "I checked the complete invoice composition against the original.",
      })
      .check();
    await page
      .getByRole("button", { name: "Save review and calculate" })
      .click();
    await expect(page.getByTestId("guest-requested")).toHaveText("$6,200.00");
    await expect(page.getByTestId("guest-remaining")).toHaveText("$5,000.00");
    await page
      .getByRole("button", { name: /View calculation · revision/ })
      .first()
      .click();
    const downloadEvent = page.waitForEvent("download", { timeout: 120_000 });
    await page
      .getByRole("button", { name: "Download calculation PDF", exact: true })
      .click();
    const pdf = await downloadEvent;
    const saved = info.outputPath("ordinary.pdf");
    await pdf.saveAs(saved);
    const inspected = spawnSync(
      path.resolve(
        process.platform === "win32"
          ? ".venv/Scripts/python.exe"
          : ".venv/bin/python",
      ),
      ["tools/inspect_guest_pdf.py", saved],
      { encoding: "utf8" },
    );
    expect(inspected.status, inspected.stderr).toBe(0);
    const text = JSON.parse(inspected.stdout).text as string;
    for (const label of [
      "Wall painting",
      "Floor protection",
      "Skirting board installation",
      "$6,200.00",
      "$5,000.00",
      "p. 1",
      "manual",
      "FICTIONAL EXAMPLE",
    ])
      expect(text).toContain(label);
    expect(text).not.toContain("source unavailable");
    await fs.mkdir("planning/screenshots/stage10", { recursive: true });
    await page
      .getByRole("region", { name: "Historical calculation" })
      .scrollIntoViewIfNeeded();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `planning/screenshots/stage10/ordinary-${info.project.name}.png`,
    });
    if (process.env.RENOTRACE_BASE_URL && info.project.name === "guest-1440") {
      await fs.copyFile(saved, "output/pdf/renotrace-stage10-ordinary.pdf");
    }
  } finally {
    await page.getByRole("button", { name: "Delete my review" }).click();
    await expect(
      page.getByRole("heading", { name: "Your review has been deleted." }),
    ).toBeVisible();
  }
});
