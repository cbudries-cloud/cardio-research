// Build-time loader for the public research directory. Pages are statically generated, so the
// running notebook never reads files and never touches the private records database.
import fs from "node:fs";
import path from "node:path";

const ROOT = process.env.RESEARCH_DIR ?? path.resolve(process.cwd(), "../../research");

export interface SourceLocation {
  section: string;
  element: string;
  quote: string;
}

export interface Claim {
  id: string;
  statement: string;
  kind: "descriptive" | "association" | "randomized_effect" | "model_estimate";
  measure: string;
  scale: "absolute" | "relative" | "descriptive";
  value: number | null;
  lower?: number | null;
  upper?: number | null;
  decimals: number;
  unit: string;
  interval?: string | null;
  comparison: string;
  population: string;
  time_horizon?: string | null;
  provenance: "reported" | "derived";
  source_location?: SourceLocation | null;
  derivation?: { method: string; inputs: string[]; explanation: string } | null;
}

export interface Evidence {
  id: string;
  short_title: string;
  citation: {
    authors: string[];
    title: string;
    journal: string;
    year: number;
    volume?: string;
    issue?: string;
    pages?: string;
    doi: string;
    pmid: string;
    pmcid?: string;
    url: string;
  };
  access: {
    full_text_reviewed: boolean;
    full_text_source: string | null;
    license: string | null;
    supplement_reviewed: boolean;
    retrieved_on: string;
    abstract_only_note: string | null;
  };
  study: {
    design: string;
    design_detail: string;
    evidence_type: "observational_association" | "randomized_comparison";
    population: string;
    setting: string;
    sample_size: number;
    exposure_or_intervention: string;
    comparator: string;
    outcomes: string[];
    follow_up: string;
  };
  claims: Claim[];
  findings_summary: string;
  limitations: { text: string; source: "stated_by_authors" | "identified_in_review" }[];
  applicability_constraints: string[];
  discrepancies: { description: string; locations: string[]; handling: string }[];
  interpretation: string;
  review: { status: string; verified_by: string; verified_on: string; method: string; independent_review: boolean };
  publication: { status: string };
}

export interface Question {
  id: string;
  question: string;
  evidence_ids: string[];
  motivation: string;
  project_connection: string;
  required_personal_observations: { observation: string; why: string; currently_available: string }[];
  decision_relevance: { if_observed: string; would_change: string }[];
  what_remains_uncertain: string[];
  what_cannot_be_concluded: string[];
  personal_applicability: { status: "not_assessed" | "assessed"; reason: string };
  chart_ids: string[];
}

export interface ChartRow {
  row_id: string;
  claim_id: string;
  group: string;
  label: string;
  series: string;
  value: number | null;
  lower: number | null;
  upper: number | null;
  decimals: number;
  // Values exactly as stored in the CSV (reported precision), for labels.
  valueText: string;
  lowerText: string;
  upperText: string;
  unit: string;
  provenance: string;
  source_section: string;
  source_element: string;
}

export interface Chart {
  id: string;
  evidence_id: string;
  title: string;
  chart_type: "range_bars" | "paired_bars" | "interval_points";
  data_file: string;
  x_label: string;
  y_label: string;
  caption: string;
  reading_note: string;
  reference_line?: { value: number; label: string } | null;
  rows: ChartRow[];
}

export interface BuildNote {
  id: string;
  date: string;
  title: string;
  kind: string;
  summary: string;
  results: { check: string; result: string; scope: string }[];
  what_this_is_not: string[];
  limitations: string[];
  next_steps: string[];
}

function readJsonDir<T>(dir: string): T[] {
  const full = path.join(ROOT, dir);
  if (!fs.existsSync(full)) return [];
  return fs
    .readdirSync(full)
    .filter((f) => f.endsWith(".json"))
    .sort()
    .map((f) => JSON.parse(fs.readFileSync(path.join(full, f), "utf8")) as T);
}

export function parseCsv(text: string): Record<string, string>[] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') {
        cell += '"';
        i++;
      } else if (ch === '"') quoted = false;
      else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") {
      row.push(cell);
      cell = "";
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else cell += ch;
  }
  if (cell !== "" || row.length) {
    row.push(cell);
    rows.push(row);
  }
  const [header, ...body] = rows.filter((r) => r.some((c) => c !== ""));
  return body.map((r) => Object.fromEntries(header.map((h, i) => [h, r[i] ?? ""])));
}

const num = (s: string) => (s === "" ? null : Number(s));

let cache: { evidence: Evidence[]; questions: Question[]; charts: Chart[]; buildNotes: BuildNote[] } | null = null;

export function loadResearch() {
  if (cache) return cache;
  const evidence = readJsonDir<Evidence>("evidence");
  const questions = readJsonDir<Question>("questions");
  const buildNotes = readJsonDir<BuildNote>("build-notes").sort((a, b) => b.date.localeCompare(a.date));
  const charts = readJsonDir<Omit<Chart, "rows">>("charts").map((c) => {
    const rows = parseCsv(fs.readFileSync(path.join(ROOT, "charts", c.data_file), "utf8")).map((r) => ({
      ...(r as unknown as ChartRow),
      value: num(r.value),
      lower: num(r.lower),
      upper: num(r.upper),
      decimals: Number(r.decimals),
      valueText: r.value,
      lowerText: r.lower,
      upperText: r.upper,
    }));
    return { ...c, rows };
  });
  // Build-time guard (the Python validator is authoritative): chart rows must equal their claims,
  // and no question may claim personal applicability.
  for (const c of charts) {
    const ev = evidence.find((e) => e.id === c.evidence_id);
    if (!ev) throw new Error(`chart ${c.id}: unknown evidence ${c.evidence_id}`);
    for (const r of c.rows) {
      const claim = ev.claims.find((x) => x.id === r.claim_id);
      if (!claim) throw new Error(`chart ${c.id}: unknown claim ${r.claim_id}`);
      for (const k of ["value", "lower", "upper"] as const) {
        if ((claim[k] ?? null) !== r[k]) throw new Error(`chart ${c.id} row ${r.row_id}: ${k} differs from claim`);
      }
    }
  }
  for (const q of questions) {
    if (q.personal_applicability.status !== "not_assessed") throw new Error(`question ${q.id}: applicability must be not_assessed`);
  }
  cache = { evidence, questions, charts, buildNotes };
  return cache;
}

export function entryFor(questionId: string) {
  const { evidence, questions, charts } = loadResearch();
  const question = questions.find((q) => q.id === questionId);
  if (!question) return null;
  return {
    question,
    evidence: question.evidence_ids.map((id) => evidence.find((e) => e.id === id)!),
    charts: question.chart_ids.map((id) => charts.find((c) => c.id === id)!),
  };
}

export function formatNumber(v: number | null | undefined, decimals?: number) {
  if (v === null || v === undefined) return "";
  if (decimals === undefined) return Number.isInteger(v) && Math.abs(v) >= 1000 ? v.toLocaleString("en-US") : String(v);
  const s = v.toFixed(decimals);
  return decimals === 0 && Math.abs(v) >= 1000 ? Number(s).toLocaleString("en-US") : s;
}

export function citationText(e: Evidence) {
  const c = e.citation;
  const authors = c.authors.length > 3 ? `${c.authors.slice(0, 3).join(", ")}, et al.` : c.authors.join(", ");
  return `${authors} ${c.title}. ${c.journal}. ${c.year};${c.volume ?? ""}${c.issue ? `(${c.issue})` : ""}${c.pages ? `:${c.pages}` : ""}.`;
}
