// Browser-level test of the complete verified-record workflow against a fresh stack
// (run via scripts/e2e.sh). Uses synthetic fixtures only.
import { expect, test, type Page } from "@playwright/test";

const FIX = process.env.E2E_FIXTURES ?? "/fixtures/synthetic";
const SHOTS = process.env.E2E_SCREENSHOTS ?? "./test-results/screens";

async function upload(page: Page, file: string, opts: { dateOrder?: string } = {}) {
  await page.goto("/documents");
  await page.setInputFiles("#file", `${FIX}/${file}`);
  if (opts.dateOrder) await page.selectOption("#date_order", opts.dateOrder);
  await page.getByRole("button", { name: "Upload and extract" }).click();
  const status = page.getByRole("status");
  await expect(status).toContainText(file);
  return status;
}

async function openCandidate(page: Page, docFile: string, testName: string) {
  await page.goto("/documents");
  await page.getByRole("link", { name: docFile, exact: true }).first().click();
  await page.getByRole("row").filter({ hasText: testName }).first().getByRole("link", { name: "Review" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(testName);
}

async function acceptHere(page: Page) {
  await page.getByLabel("I compared every value above with the source and they match.").check();
  await page.getByRole("button", { name: "Accept" }).click();
  await expect(page.locator('[data-status="accepted"]').first()).toBeVisible();
  await expect(page.getByTestId("calc-eligibility")).toHaveText("Available to calculations");
}

test("upload, extract, source review, correction, acceptance, longitudinal display", async ({ page, request }) => {
  // 1. Upload a text PDF: candidates are created, none accepted.
  const status = await upload(page, "synthetic_lab_report_2024.pdf");
  await expect(status).toContainText("8 candidate(s) extracted");
  let inputs = await (await request.get("/api/v1/calculation-inputs/observations")).json();
  expect(inputs).toEqual([]);

  // 2. Source review: the PDF line is shown beside the extracted values.
  await openCandidate(page, "synthetic_lab_report_2024.pdf", "LDL Cholesterol (calculated)");
  await expect(page.getByTestId("source-pdf")).toContainText("LDL Cholesterol (calculated) 131 H mg/dL <100");
  await expect(page.locator(".source-page img")).toBeVisible();
  await expect(page.locator(".source-page .hl")).toBeVisible();
  await expect(page.getByTestId("fields")).toContainText("131");
  await expect(page.getByTestId("calc-eligibility")).toHaveText("Not available to calculations");
  await page.screenshot({ path: `${SHOTS}/01-source-review-pdf.png`, fullPage: true });
  await acceptHere(page);
  inputs = await (await request.get("/api/v1/calculation-inputs/observations")).json();
  expect(inputs).toHaveLength(1);
  expect(inputs[0].value).toBe(131);

  // 2b. Mixed report: HbA1c inherits "Specimen: Serum" from the header -> SPEC-1 conflict, blocked.
  await openCandidate(page, "synthetic_lab_report_2024.pdf", "Hemoglobin A1c");
  await expect(page.getByTestId("inherited")).toContainText("Specimen: Serum");
  await expect(page.getByTestId("fields")).toContainText("serum (report header)");
  await expect(page.getByText("Specimen conflicts with this analyte (rule SPEC-1)")).toBeVisible();
  await expect(page.getByRole("button", { name: "Accept" })).toBeDisabled();
  await page.screenshot({ path: `${SHOTS}/01b-specimen-conflict.png`, fullPage: true });

  // 3. Edge-case CSV: a missing unit blocks acceptance until corrected.
  await upload(page, "synthetic_edge_cases.csv");
  await openCandidate(page, "synthetic_edge_cases.csv", "Triglycerides");
  await expect(page.getByTestId("source-csv")).toContainText("Row 2");
  await expect(page.getByText("cannot be accepted until the blocking issues are corrected")).toBeVisible();
  await expect(page.getByRole("button", { name: "Accept" })).toBeDisabled();
  await page.getByRole("button", { name: "Correct a value" }).click();
  await page.getByLabel("Unit (as written)").fill("mg/dL");
  await page.getByLabel("Reason (required)").fill("Unit is printed in the column header of the source");
  await page.getByRole("button", { name: /Save correction \(1 field/ }).click();
  await expect(page.getByText("Participant correction of")).toBeVisible();
  await expect(page.getByText("Earlier versions")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/02-correction.png`, fullPage: true });
  await acceptHere(page);
  await expect(page.getByRole("row").filter({ hasText: "observation corrected" })).toContainText('null -> "mg/dL"');

  // 4. Ambiguous date: resolved by the participant, raw text kept.
  await openCandidate(page, "synthetic_edge_cases.csv", "HDL Cholesterol");
  await expect(page.getByTestId("fields")).toContainText("04/06/2024");
  await page.getByRole("button", { name: "Correct a value" }).click();
  await page.getByLabel("Collection date").fill("2024-06-04");
  await page.getByLabel("Reason (required)").fill("Source uses day-first dates");
  await page.getByRole("button", { name: /Save correction/ }).click();
  await expect(page.getByTestId("fields")).toContainText("2024-06-04 (participant resolved)");
  await acceptHere(page);

  // 5. Lab-corrected report: flagged, linked only after explicit resolution.
  const s2 = await upload(page, "synthetic_lab_report_2024_corrected.pdf");
  await expect(s2).toContainText("8 candidate(s) extracted");
  inputs = await (await request.get("/api/v1/calculation-inputs/observations?normalized_test_name=ldl_cholesterol")).json();
  expect(inputs).toEqual([]); // the accepted LDL is withheld while the question is open
  await page.goto("/review");
  const corr = page.locator('[data-flag-kind="possible_lab_correction"]');
  await expect(corr).toHaveCount(1);
  await expect(corr.getByTestId("match-basis")).toContainText("same accession");
  await page.screenshot({ path: `${SHOTS}/03-review-queue.png`, fullPage: true });
  await corr.getByLabel("Resolution note").fill("Lab issued corrected report on 2024-01-19");
  await corr.getByRole("button", { name: "Newer one replaces the earlier one" }).click();
  await expect(page.locator('[data-flag-kind="possible_lab_correction"]')).toHaveCount(0);

  await openCandidate(page, "synthetic_lab_report_2024_corrected.pdf", "LDL Cholesterol (calculated)");
  await expect(page.getByText("Laboratory-issued correction of")).toBeVisible();
  await acceptHere(page);
  inputs = await (await request.get("/api/v1/calculation-inputs/observations?normalized_test_name=ldl_cholesterol")).json();
  expect(inputs.map((i: { value: number }) => i.value)).toEqual([127]);

  // 6. Image-only PDF: explicit limitation and manual entry path.
  const s3 = await upload(page, "synthetic_scanned_image_only.pdf");
  await expect(s3).toContainText("0 candidate(s) extracted");
  await expect(s3).toContainText("OCR is not implemented");
  await s3.getByRole("link", { name: "Open document" }).click();
  await page.getByRole("link", { name: "Enter a value manually from this document" }).click();
  await expect(page.locator(".source-page img")).toBeVisible();
  await page.getByLabel("Test name (as written) *").fill("Cholesterol, Total");
  await page.getByLabel("Value (as written) *").fill("201");
  await page.getByLabel("Unit (as written)").fill("mg/dL");
  await page.getByLabel("Collection date").fill("2021-11-02");
  await page.getByLabel("Collection method").selectOption("venous");
  await page.getByLabel("Page in source").fill("1");
  await page.getByRole("button", { name: "Create candidate" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Cholesterol, Total");
  await expect(page.getByTestId("source-manual")).toContainText("Entered manually from page 1");
  await acceptHere(page);

  // 7. Capillary results stay a separate series.
  await upload(page, "synthetic_fingerprick_2023.csv");
  await openCandidate(page, "synthetic_fingerprick_2023.csv", "Total Cholesterol");
  await expect(page.getByTestId("fields")).toContainText("capillary (stated in source)");
  await acceptHere(page);

  // 8. Longitudinal display.
  await page.goto("/trends");
  await page.getByRole("button", { name: /^total cholesterol/ }).click();
  const series = page.getByTestId("series");
  await expect(series).toHaveCount(2);
  await expect(page.locator('[data-testid="series"][data-method="capillary"]')).toContainText("2023-03-14");
  await expect(page.locator('[data-testid="series"][data-method="venous"]')).toContainText("2021-11-02");
  await expect(page.getByText("Capillary and venous results are shown as separate series")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/04-trends.png`, fullPage: true });

  // 9. Overview reflects outstanding review honestly.
  await page.goto("/");
  await expect(page.getByRole("link", { name: /\d+ awaiting review/ }).first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/05-overview.png`, fullPage: true });

  // 10. Records app remains usable at phone width (tables scroll inside their containers).
  await page.setViewportSize({ width: 390, height: 844 });
  for (const p of ["/", "/documents", "/review", "/trends"]) {
    await page.goto(p);
    const { sw, iw } = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth }));
    expect(sw, `${p} must not scroll horizontally`).toBeLessThanOrEqual(iw + 1);
  }
  await page.goto("/review");
  await page.screenshot({ path: `${SHOTS}/06-review-mobile.png`, fullPage: true });
  await page.setViewportSize({ width: 1280, height: 800 });

  // Final check: every calculation input is accepted; nothing unverified leaks.
  const all = await (await request.get("/api/v1/observations")).json();
  const accepted = new Set(all.filter((o: { verification_status: string }) => o.verification_status === "accepted").map((o: { id: string }) => o.id));
  inputs = await (await request.get("/api/v1/calculation-inputs/observations")).json();
  expect(inputs.length).toBeGreaterThan(0);
  for (const i of inputs) expect(accepted.has(i.observation_id)).toBe(true);
});

test("baseline page renders a snapshot from synthetic records", async ({ page }) => {
  await page.goto("/baseline");
  await page.getByRole("button", { name: "Create new snapshot from current records" }).click();
  await expect(page.getByText(/Snapshot v\d+/)).toBeVisible();
  await expect(page.getByRole("heading", { name: /Rules-based baseline v0\.1 \(\d+\)/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Research workflow v0\.2/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Readiness issues \(not risk findings\)/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: /First testable question/ })).toBeVisible();
  await expect(page.getByText("Language-model reasoning in the runtime")).toBeVisible();
});

test("investigation page gates the live run and never exposes a key", async ({ page }) => {
  await page.goto("/investigation");
  await expect(page.getByRole("heading", { name: /live investigation/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "2. Provider" })).toBeVisible();
  // e2e stacks use the labelled fake provider (D-058); the missing-key path is covered by test_live_run.py
  await expect(page.getByRole("cell", { name: "fake", exact: true })).toBeVisible();
  await expect(page.getByText(/sk-/)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Approve and send once" })).toHaveCount(0);
});
