import Link from "next/link";
import { notFound } from "next/navigation";
import { ChartView } from "@/components/ChartView";
import { citationText, entryFor, formatNumber, loadResearch, type Claim, type Evidence } from "@/lib/research";

export function generateStaticParams() {
  return loadResearch().questions.map((q) => ({ id: q.id }));
}

export const dynamicParams = false;

const KIND_TEXT: Record<Claim["kind"], string> = {
  descriptive: "Descriptive",
  association: "Observational association",
  randomized_effect: "Randomized comparison",
  model_estimate: "Model-based estimate",
};

function claimValue(c: Claim) {
  const f = (v: number | null | undefined) => formatNumber(v, c.decimals);
  if (c.value === null) return `${f(c.lower)} to ${f(c.upper)}`;
  const ci = c.lower !== null && c.lower !== undefined ? ` (${f(c.lower)} to ${f(c.upper)})` : "";
  return `${f(c.value)}${ci}`;
}

export default async function EntryPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const entry = entryFor(id);
  if (!entry) notFound();
  const { question: q, evidence, charts } = entry;

  return (
    <article className="entry stack">
      <p className="muted">
        <Link href="/">Entries</Link> /
      </p>
      <h1>{q.question}</h1>
      {evidence.map((e) => (
        <p key={e.id} className="citation">
          {citationText(e)} <a href={e.citation.url}>doi:{e.citation.doi}</a> ·{" "}
          <a href={`https://pubmed.ncbi.nlm.nih.gov/${e.citation.pmid}/`}>PubMed {e.citation.pmid}</a>
          {e.citation.pmcid && (
            <>
              {" "}· <a href={`https://pmc.ncbi.nlm.nih.gov/articles/${e.citation.pmcid}/`}>{e.citation.pmcid}</a>
            </>
          )}
        </p>
      ))}

      <div className="callout" data-testid="applicability">
        <strong>Personal applicability: not assessed.</strong> {q.personal_applicability.reason}
      </div>

      <section data-testid="section-found">
        <h2>What the study found</h2>
        {evidence.map((e) => (
          <div key={e.id}>
            <p>{e.findings_summary}</p>
            <p className="muted">
              {e.study.evidence_type === "randomized_comparison"
                ? "Design: randomized comparison. Differences between treatments within the trial can be read as effects of the treatments under the trial's conditions."
                : "Design: observational. These are associations; they do not show that changing the exposure would change the outcome."}
            </p>
          </div>
        ))}
        {charts.map((c) => (
          <ChartView key={c.id} chart={c} />
        ))}
      </section>

      <section data-testid="section-uncertain">
        <h2>What remains uncertain</h2>
        <ul>
          {q.what_remains_uncertain.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
      </section>

      <section data-testid="section-why">
        <h2>Why it matters to this project</h2>
        <p>{q.motivation}</p>
        <p>{q.project_connection}</p>
      </section>

      <section data-testid="section-data-needed">
        <h2>Personal data needed to investigate applicability</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Observation</th>
                <th>Why it is needed</th>
                <th>Available now</th>
              </tr>
            </thead>
            <tbody>
              {q.required_personal_observations.map((o) => (
                <tr key={o.observation}>
                  <td>{o.observation}</td>
                  <td>{o.why}</td>
                  <td>{o.currently_available === "not_imported" ? "Not imported" : o.currently_available === "unknown" ? "Unknown" : "No"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <h3>What different observations could change</h3>
        <ul>
          {q.decision_relevance.map((d) => (
            <li key={d.if_observed}>
              <strong>If</strong> {d.if_observed}: {d.would_change}
            </li>
          ))}
        </ul>
      </section>

      <section data-testid="section-cannot">
        <h2>What cannot yet be concluded</h2>
        <ul>
          {q.what_cannot_be_concluded.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
      </section>

      {evidence.map((e) => (
        <EvidenceDetail key={e.id} e={e} />
      ))}
    </article>
  );
}

function EvidenceDetail({ e }: { e: Evidence }) {
  const derived = e.claims.filter((c) => c.provenance === "derived");
  return (
    <section className="stack" data-testid="evidence-detail">
      <h2>Interpretation</h2>
      <div className="interpretation">
        <span className="kicker">Our reading, separate from what the paper reports</span>
        <p>{e.interpretation}</p>
      </div>

      <details className="methods" data-testid="methods">
        <summary>Methods: study design, population and limitations</summary>
        <dl>
          <dt>Design</dt>
          <dd>{e.study.design_detail}</dd>
          <dt>Population</dt>
          <dd>
            {e.study.population}. {e.study.setting}. n = {formatNumber(e.study.sample_size)}.
          </dd>
          <dt>Exposure or intervention</dt>
          <dd>{e.study.exposure_or_intervention}</dd>
          <dt>Comparator</dt>
          <dd>{e.study.comparator}</dd>
          <dt>Outcome</dt>
          <dd>{e.study.outcomes.join("; ")}</dd>
          <dt>Follow-up</dt>
          <dd>{e.study.follow_up}</dd>
        </dl>
        <h3>Limitations</h3>
        <ul>
          {e.limitations.map((l) => (
            <li key={l.text}>
              {l.text} <span className="muted">({l.source === "stated_by_authors" ? "stated by the authors" : "identified in this review"})</span>
            </li>
          ))}
        </ul>
        <h3>Applicability constraints</h3>
        <ul>
          {e.applicability_constraints.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
        {e.discrepancies.length > 0 && (
          <>
            <h3>Discrepancies found in the source</h3>
            <ul>
              {e.discrepancies.map((d) => (
                <li key={d.description}>
                  {d.description} <span className="muted">Handling: {d.handling}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </details>

      <details className="methods" data-testid="sources">
        <summary>Source verification: every number with its quote ({e.claims.length} claims)</summary>
        <p className="muted">
          Access: {e.access.full_text_reviewed ? "full text reviewed" : "abstract only"} ({e.access.full_text_source}
          {e.access.license ? `, ${e.access.license}` : ""}); supplement {e.access.supplement_reviewed ? "reviewed" : "not reviewed"}; retrieved{" "}
          {e.access.retrieved_on}. Review status: {e.review.status.replace("_", " ")} by {e.review.verified_by} on {e.review.verified_on}.{" "}
          {e.review.method}
        </p>
        <div className="table-wrap">
          <table className="claims">
            <colgroup>
              <col style={{ width: "30%" }} />
              <col style={{ width: "18%" }} />
              <col style={{ width: "14%" }} />
              <col style={{ width: "38%" }} />
            </colgroup>
            <thead>
              <tr>
                <th>Claim</th>
                <th>Value</th>
                <th>Type</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {e.claims.map((c) => (
                <tr key={c.id} id={`claim-${c.id}`}>
                  <td>
                    {c.statement}
                    <div className="muted">
                      {c.comparison}. {c.population}
                      {c.time_horizon ? `. ${c.time_horizon}` : ""}.
                    </div>
                  </td>
                  <td className="num">
                    {claimValue(c)}
                    <div className="muted">
                      {c.unit}
                      {c.interval ? `; ${c.interval}` : ""}
                    </div>
                  </td>
                  <td>
                    {KIND_TEXT[c.kind]}; {c.scale} scale
                    {c.provenance === "derived" && <div className="badge">our calculation</div>}
                  </td>
                  <td>
                    {c.source_location ? (
                      <>
                        <span className="muted">
                          {c.source_location.section}, {c.source_location.element}
                        </span>
                        <blockquote>{c.source_location.quote}</blockquote>
                      </>
                    ) : (
                      <span>{c.derivation?.explanation}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {derived.length > 0 && (
          <p className="muted">Rows marked "our calculation" are arithmetic on reported values, not results reported by the authors.</p>
        )}
      </details>
    </section>
  );
}
