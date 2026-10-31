import Link from "next/link";
import { loadResearch } from "@/lib/research";

export default function Overview() {
  const { questions, evidence, buildNotes } = loadResearch();
  return (
    <div className="stack">
      <section className="intro">
        <h1>What the evidence says, and what it cannot say yet</h1>
        <p>
          Each entry starts from a research question, verifies a primary study against its full text, and shows the
          numbers with their exact source locations. Every entry keeps four things apart: what the study found, what
          remains uncertain, why it matters to this project, and what cannot be concluded.
        </p>
        <div className="callout">
          <strong>Research findings, not personal findings.</strong> Cohort event rates and trial averages describe the
          studied populations. No personal medical records have been imported or verified, so personal applicability
          is <em>not assessed</em> for every entry.
        </div>
      </section>

      <section>
        <h2>Entries</h2>
        <div className="cards">
          {questions.map((q) => {
            const ev = evidence.filter((e) => q.evidence_ids.includes(e.id));
            return (
              <Link key={q.id} href={`/entries/${q.id}`} className="card" data-testid="entry-card">
                <span className="kicker">
                  {ev.map((e) => `${e.citation.authors[0].split(" ")[0]} et al., ${e.citation.journal} ${e.citation.year}`).join("; ")}
                </span>
                <h3>{q.question}</h3>
                <p>{ev[0]?.findings_summary.split(". ").slice(0, 2).join(". ")}.</p>
                <div className="badges">
                  {ev.map((e) => (
                    <span key={e.id} className="badge">
                      {e.study.evidence_type === "randomized_comparison" ? "Randomized trial" : "Observational"}
                    </span>
                  ))}
                  <span className="badge">{ev.every((e) => e.access.full_text_reviewed) ? "Full text checked" : "Abstract only"}</span>
                  <span className="badge muted">Personal applicability: not assessed</span>
                </div>
              </Link>
            );
          })}
        </div>
      </section>

      <section>
        <h2>Build log</h2>
        <p className="muted">Software progress is recorded separately from scientific evidence.</p>
        <ul className="plain">
          {buildNotes.map((b) => (
            <li key={b.id}>
              <Link href="/build">{b.title}</Link> <span className="muted">({b.date})</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
