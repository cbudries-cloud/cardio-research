// Named zz- so it runs after workflow.spec.ts, whose first test needs an empty record (workers: 1, file order).
// The research-partner journey in the browser, on synthetic records and the labelled fake provider (D-058):
// overview -> question with the records it used -> approval -> answer -> investigation -> next step and protocol ->
// preserved, locked prediction -> new information -> a new version that keeps the earlier one.
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const SHOTS = process.env.E2E_SCREENSHOTS ?? "./test-results/screens";
const H = { "X-Cardio-Client": "web" };
const CSV = "Test,Result,Units,Collection Date,Lab,Reference Range,Flag,Method,Accession\n" +
  "Apolipoprotein B,88,mg/dL,2022-05-05,SYA,<90,,,ACCJ0001\n" +
  "LDL Cholesterol (direct),118,mg/dL,2022-05-05,SYA,<100,H,,ACCJ0001\n" +
  "Apolipoprotein B,79,mg/dL,2024-05-07,SYA,<90,,,ACCJ0002\n" +
  "LDL Cholesterol (direct),101,mg/dL,2024-05-07,SYA,<100,H,,ACCJ0002\n";

async function seed(request: APIRequestContext) {
  const r = await request.post("/api/v1/documents", {
    headers: H, multipart: { file: { name: "journey.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) } },
  });
  expect(r.status()).toBe(201);
  const doc = await r.json();
  expect((await request.post(`/api/v1/documents/${doc.id}/auto-accept`, { headers: H })).status()).toBe(200);
}

async function approve(page: Page) {
  const panel = page.getByTestId("approval").first();
  await panel.getByTestId("approve-check").check();
  await panel.getByRole("button", { name: "Approve and send once" }).click();
}

async function addContext(page: Page, domain: string, value: string) {
  await page.goto("/context");
  const section = page.getByTestId(`context-${domain}`);
  await section.getByRole("button", { name: "Add", exact: true }).first().click();
  await section.getByTestId("context-value").fill(value);
  await section.getByRole("button", { name: "Save" }).click();
  await expect(section.getByText(value, { exact: true })).toBeVisible();
}

test("overview, question, investigation, protocol, prediction and an updated version", async ({ page, request }) => {
  test.setTimeout(120_000);
  await seed(request);

  // 1. The overview starts from the record: what it shows, cannot establish, and what deserves investigation.
  await page.goto("/");
  const head = page.getByTestId("headline");
  await expect(head.getByRole("heading", { name: "What the records show" })).toBeVisible();
  await expect(head.getByText(/not an assessment of cardiovascular risk/)).toBeVisible();
  await expect(page.getByTestId("domain-lipids").getByText("measured", { exact: true })).toBeVisible();
  await expect(page.getByTestId("domain-blood_pressure").getByText("unknown", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Atherogenic lipoprotein exposure over the available history" })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/10-overview.png`, fullPage: true });

  // 2. Missing context is collected in the app.
  await addContext(page, "blood_pressure", "126/80");

  // 3. A question shows the records it would use and waits for approval.
  await page.goto("/ask");
  await page.getByRole("button", { name: /What does my history establish/ }).click();
  await page.getByRole("button", { name: "Prepare question" }).click();
  const turn = page.getByTestId("turn").first();
  await expect(turn.getByTestId("retrieval")).toContainText("Records used");
  await expect(turn.getByTestId("approval")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/11-question-approval.png`, fullPage: true });
  await approve(page);
  const answer = turn.getByTestId("answer");
  await expect(answer).toContainText("FAKE PROVIDER", { timeout: 15_000 });
  await expect(answer.getByTestId("citation-check")).toBeVisible();
  await answer.getByRole("button", { name: "Keep" }).first().click();
  await expect(answer.getByText("kept", { exact: true })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/12-answer.png`, fullPage: true });

  // 4. Select a research question; approve the investigation.
  await page.goto("/research");
  const prio = page.getByTestId("priority-lipid-exposure");
  await expect(prio.getByText("Why it is relevant")).toBeVisible();
  await prio.getByRole("button", { name: "Investigate this question" }).click();
  const inv = page.getByTestId("investigation");
  await expect(inv.getByTestId("approval")).toBeVisible();
  await approve(page);
  await expect(inv.getByTestId("investigation-result")).toContainText("Canned investigation summary", { timeout: 15_000 });
  await expect(inv.getByRole("heading", { name: "What interpretation changed, and why" })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/13-investigation.png`, fullPage: true });

  // 5. Next investigation: three kinds of next step and one candidate protocol, preserved and locked.
  await page.goto("/next");
  await expect(page.getByRole("heading", { name: "History you can supply" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Questions for clinical review" })).toBeVisible();
  await expect(page.getByTestId("protocol")).toContainText("Counts against the hypothesis");
  await page.getByRole("button", { name: "Preserve as a draft prediction" }).click();
  const pred = page.getByTestId("prediction").first();
  await expect(pred).toContainText("draft, not locked");
  await pred.getByRole("checkbox").check();
  await pred.getByRole("button", { name: "Lock" }).click();
  await expect(pred).toContainText(/locked \d/);
  await page.screenshot({ path: `${SHOTS}/14-next-protocol.png`, fullPage: true });

  // 6. New information arrives: the investigation says so, and a new version keeps the earlier one.
  await addContext(page, "medications", "None");
  await page.goto("/research");
  await page.getByTestId("priority-lipid-exposure").getByRole("button", { name: /Open investigation/ }).click();
  await expect(page.getByTestId("new-information")).toContainText("1 context");
  await page.getByTestId("priority-lipid-exposure").getByRole("button", { name: "Prepare a new version" }).click();
  await expect(page.getByTestId("version")).toHaveCount(2);
  await approve(page);
  await expect(page.getByTestId("investigation-result")).toHaveCount(2, { timeout: 15_000 });
  await expect(page.getByTestId("new-information")).toHaveCount(0);
  await page.screenshot({ path: `${SHOTS}/15-versions.png`, fullPage: true });
});
