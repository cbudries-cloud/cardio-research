export default function Methods() {
  return (
    <div className="stack prose">
      <h1>Methods</h1>
      <h2>How an entry is built</h2>
      <ol>
        <li>A research question is written first, together with what personal observations would be needed and what each could change.</li>
        <li>The primary study is retrieved by DOI from PubMed and PubMed Central. Whether the full text or only the abstract was reviewed is recorded.</li>
        <li>Each number used is stored as a claim with a verbatim quote and its location (section, paragraph or table row).</li>
        <li>An automated validator checks that every reported number appears in its quote, and that every quote appears verbatim in the retrieved full text. Our own calculations are stored separately, with the formula, and are recomputed.</li>
        <li>Chart inputs are saved as CSV with a claim reference and source location per row. Charts are drawn only from those files, and each row must equal its claim.</li>
        <li>Interpretation is written in a separate field from the reported findings.</li>
      </ol>
      <h2>Distinctions kept in every entry</h2>
      <ul>
        <li>Observational associations vs randomized comparisons.</li>
        <li>Absolute event rates vs relative effects (hazard ratios).</li>
        <li>Reported results vs our own arithmetic.</li>
        <li>Estimated benefits that hold if a fitted model is true vs demonstrated benefits.</li>
        <li>Study populations vs the project participant: cohort rates are never presented as personal risk.</li>
      </ul>
      <h2>What the review status means</h2>
      <p>
        “Source verified” means an automated agent matched each value to the source text and the validator passed. It
        is not peer review, not an independent check by a clinician or statistician, and not a judgement that the
        study's conclusions are correct.
      </p>
      <h2>Separation from personal records</h2>
      <p>
        This notebook is a separate application. It is generated from the public <code>research/</code> directory at
        build time, has no connection to the private records database, and contains no personal health data.
      </p>
    </div>
  );
}
