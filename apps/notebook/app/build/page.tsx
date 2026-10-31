import { loadResearch } from "@/lib/research";

export default function BuildLog() {
  const { buildNotes } = loadResearch();
  return (
    <div className="stack">
      <h1>Build log</h1>
      <div className="callout">
        Software progress, recorded separately from the scientific entries. Results below come from internal
        automated software tests. They are not external review and not clinical validation.
      </div>
      {buildNotes.map((b) => (
        <article key={b.id} className="stack" data-testid="build-note">
          <h2>{b.title}</h2>
          <p className="muted">{b.date}</p>
          <p>{b.summary}</p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Check</th>
                  <th>Result</th>
                  <th>What it does and does not establish</th>
                </tr>
              </thead>
              <tbody>
                {b.results.map((r) => (
                  <tr key={r.check}>
                    <td>{r.check}</td>
                    <td>{r.result}</td>
                    <td>{r.scope}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h3>What this is not</h3>
          <ul>
            {b.what_this_is_not.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
          <h3>Limitations</h3>
          <ul>
            {b.limitations.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
          {b.next_steps.length > 0 && (
            <>
              <h3>Next</h3>
              <ul>
                {b.next_steps.map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
            </>
          )}
        </article>
      ))}

      <section className="demo" data-testid="interface-demo">
        <h2>Interface demonstration (synthetic data)</h2>
        <p className="muted">
          Screenshots of the private records application running on invented fixtures. They show interface behaviour
          only. Every value in them is synthetic; none is a personal result or prediction.
        </p>
        <figure>
          <img src="/demo/source-review-synthetic.png" alt="Records app: synthetic lab value reviewed beside its highlighted source line" />
          <figcaption>Source review: an extracted candidate beside the highlighted line in a synthetic PDF.</figcaption>
        </figure>
        <figure>
          <img src="/demo/specimen-conflict-synthetic.png" alt="Records app: synthetic HbA1c candidate blocked by a specimen conflict" />
          <figcaption>Integrity rule: a synthetic HbA1c row inheriting “Specimen: Serum” is blocked until reviewed.</figcaption>
        </figure>
      </section>
    </div>
  );
}
