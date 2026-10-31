// Browser checks for the research notebook (separate app; no private data).
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

const NB = process.env.E2E_NOTEBOOK_URL ?? "http://127.0.0.1:3100";
const RESEARCH = process.env.E2E_RESEARCH_DIR ?? "/research";
const SHOTS = process.env.E2E_SCREENSHOTS ?? "./test-results/screens";

function readJson<T>(dir: string): T[] {
  return fs
    .readdirSync(path.join(RESEARCH, dir))
    .filter((f) => f.endsWith(".json"))
    .map((f) => JSON.parse(fs.readFileSync(path.join(RESEARCH, dir, f), "utf8")) as T);
}

function parseCsv(text: string): Record<string, string>[] {
  // Chart CSVs are written by Python's csv module; fields may be quoted.
  const rows: string[][] = [];
  let row: string[] = [], cell = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) { if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; } else if (c === '"') q = false; else cell += c; }
    else if (c === '"') q = true;
    else if (c === ",") { row.push(cell); cell = ""; }
    else if (c === "\n" || c === "\r") { if (c === "\r" && text[i + 1] === "\n") i++; row.push(cell); rows.push(row); row = []; cell = ""; }
    else cell += c;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  const [h, ...b] = rows.filter((r) => r.some(Boolean));
  return b.map((r) => Object.fromEntries(h.map((k, i) => [k, r[i] ?? ""])));
}

type Q = { id: string; question: string; chart_ids: string[]; evidence_ids: string[] };
type C = { id: string; data_file: string; chart_type: string };
type E = { id: string; citation: { doi: string; pmid: string; pmcid?: string } };
const questions = readJson<Q>("questions");
const charts = Object.fromEntries(readJson<C>("charts").map((c) => [c.id, c]));
const evidence = Object.fromEntries(readJson<E>("evidence").map((e) => [e.id, e]));

async function noHorizontalOverflow(page: Page) {
  const { sw, iw } = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth }));
  expect(sw, "page must not scroll horizontally").toBeLessThanOrEqual(iw + 1);
}

test("overview lists every entry with applicability not assessed", async ({ page }) => {
  await page.goto(NB + "/");
  const cards = page.getByTestId("entry-card");
  await expect(cards).toHaveCount(questions.length);
  for (const q of questions) await expect(page.getByRole("heading", { name: q.question })).toBeVisible();
  await expect(page.getByText("Personal applicability: not assessed")).toHaveCount(questions.length);
  await expect(page.getByText("Research findings, not personal findings.")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/nb-01-overview.png`, fullPage: true });
});

for (const q of questions) {
  test(`entry ${q.id}: charts match stored inputs; sources and sections present`, async ({ page }) => {
    await page.goto(`${NB}/entries/${q.id}`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(q.question);
    await expect(page.getByTestId("applicability")).toContainText("not assessed");
    for (const id of ["section-found", "section-uncertain", "section-why", "section-data-needed", "section-cannot"]) {
      await expect(page.getByTestId(id)).toBeVisible();
    }

    // Chart values equal the CSV inputs, mark by mark.
    for (const cid of q.chart_ids) {
      const rows = parseCsv(fs.readFileSync(path.join(RESEARCH, "charts", charts[cid].data_file), "utf8"));
      const fig = page.locator(`figure[data-chart-id="${cid}"]`);
      await expect(fig).toBeVisible();
      await expect(fig.locator(".mark")).toHaveCount(rows.length);
      for (const r of rows) {
        const mark = fig.locator(`.mark[data-row-id="${r.row_id}"]`);
        await expect(mark).toHaveAttribute("data-claim-id", r.claim_id);
        for (const k of ["value", "lower", "upper"]) {
          const got = await mark.getAttribute(`data-${k}`);
          expect(got === "" ? "" : Number(got), `${cid}/${r.row_id}.${k}`).toEqual(r[k] === "" ? "" : Number(r[k]));
        }
        // Printed labels use the stored strings (reported precision), not reformatted numbers.
        for (const k of charts[cid].chart_type === "range_bars" ? ["lower", "upper"] : ["value"]) {
          const exact = new RegExp(`^${r[k].replace(/[.*+?^${}()|[\]\\-]/g, "\\$&")}$`);
          await expect(fig.locator("text.value").filter({ hasText: exact }).first(), `${cid}/${r.row_id} ${k} label`).toBeAttached();
        }
        // Source inspection: the data table row and the quoted claim are reachable.
        await expect(fig.locator(`tr[data-row-id="${r.row_id}"]`)).toHaveCount(1);
        await expect(page.locator(`#claim-${r.claim_id} blockquote, #claim-${r.claim_id} td`).first()).toBeAttached();
      }
    }

    // Source links point at the verified identifiers.
    for (const eid of q.evidence_ids) {
      const c = evidence[eid].citation;
      await expect(page.locator(`a[href="https://doi.org/${c.doi}"]`).first()).toBeVisible();
      await expect(page.locator(`a[href="https://pubmed.ncbi.nlm.nih.gov/${c.pmid}/"]`).first()).toBeVisible();
      if (c.pmcid) await expect(page.locator(`a[href="https://pmc.ncbi.nlm.nih.gov/articles/${c.pmcid}/"]`).first()).toBeVisible();
    }

    // Expandable methods and source verification open and show content.
    const sources = page.getByTestId("sources").first();
    await sources.locator("summary").click();
    await expect(sources.locator("blockquote").first()).toBeVisible();
    const methods = page.getByTestId("methods").first();
    await methods.locator("summary").click();
    await expect(methods.getByRole("heading", { name: "Limitations", exact: true })).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/nb-02-entry-${q.id}.png`, fullPage: true });

    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload();
    await noHorizontalOverflow(page);
    await page.screenshot({ path: `${SHOTS}/nb-03-entry-${q.id}-mobile.png`, fullPage: true });
  });
}

test("build log is labelled internal testing and demos are separated", async ({ page }) => {
  await page.goto(NB + "/build");
  await expect(page.getByText("not external review and not clinical validation")).toBeVisible();
  await expect(page.getByTestId("build-note").first()).toBeVisible();
  await expect(page.getByTestId("interface-demo")).toContainText("synthetic");
  await page.setViewportSize({ width: 390, height: 844 });
  await noHorizontalOverflow(page);
});

test("notebook exposes no private paths, credentials, logs or records API", async ({ page, request }) => {
  const forbidden = [/\/Users\//, /cbudries/i, /scratchpad/i, /password/i, /api[_-]?key/i, /secret/i, /BEGIN [A-Z ]*PRIVATE KEY/,
    /cardio-local-only/, /postgresql\+psycopg/, /127\.0\.0\.1:8000/, /error_id/, /Traceback/];
  const pages = ["/", "/build", "/methods", ...questions.map((q) => `/entries/${q.id}`)];
  for (const p of pages) {
    const html = await (await request.get(NB + p)).text();
    for (const re of forbidden) expect(html, `${p} must not contain ${re}`).not.toMatch(re);
  }
  for (const p of ["/api/v1/overview", "/api/v1/calculation-inputs/observations", "/api/v1/documents"]) {
    expect((await request.get(NB + p)).status(), `${p} must not exist on the notebook`).toBe(404);
  }
  await page.goto(NB + "/methods");
  await page.setViewportSize({ width: 390, height: 844 });
  await noHorizontalOverflow(page);
});
