# Founder’s brief: Personal Cardiovascular Research System
1. Product thesis
Build a standalone application that maintains an evolving, testable understanding of one person’s cardiovascular risk.

The product should answer two different questions:

“What does the available evidence suggest about the sources of this person’s risk, and what remains unexplained?”

“Given a specific intervention and measurement protocol, what does the system predict will happen, and was that prediction correct?”

The first version will investigate cardiovascular risk broadly but make quantitative predictions narrowly, one outcome at a time.

The product is not a replacement physician, a supplement recommendation engine, or a conversational medical record. It is a personal research system with persistent records, explicit hypotheses, numerical models, prospective experiments, and an audit trail.

The founding hypothesis is that an organized cycle of investigation and measurement can produce knowledge that neither a one-time medical assessment nor a one-time AI interpretation provides.

That hypothesis must be tested. More detailed explanations are not, by themselves, evidence of better understanding.
2. Initial scope and boundaries
The starting dataset consists of Function Health reports and historical finger-prick results from 2022–2024. The application must determine what those records actually contain rather than assume a particular biomarker is available.

No laboratory reports have been examined for this brief. Age, current measurements, medical history, medications, and the details of relatives’ cardiovascular events remain unverified.

Version one has three operating modes:
Mode    Permitted behavior
Investigation    Organize records, research explanations, identify contradictions, and rank unanswered questions.
Observation    Collect measurements and make prospective forecasts without directing treatment changes.
Constrained experimentation    Support ordinary, low-risk behavioral comparisons through predefined protocols, subject to eligibility and safety checks.


There is no physician participating initially. Therefore, medication changes, disease-targeted supplement regimens, genetic diagnosis, imaging decisions, and medically consequential experiments remain outside the application’s autonomous authority.

The system may investigate these subjects and prepare questions for clinical review. It must not turn a research hypothesis into instructions to begin treatment.

The absence of a physician limits what the system can act on, not how deeply it can investigate.
3. What the “personal model” actually contains
I would build three connected components rather than one model claiming to simulate the cardiovascular system.
A. A reference risk model
This applies an established population-derived risk equation when the required inputs and eligibility conditions are satisfied.

It provides a reference estimate, not a complete explanation of personal risk.

PREVENT is a candidate. Its current implementation distinguishes outcomes and time horizons, with 10-year estimates for eligible adults aged 30–79 and 30-year estimates for eligible adults aged 30–59. The application must enforce the relevant exclusions and input requirements rather than extrapolate beyond them. AHA provides its source code through a license agreement. professional.heart.org

Implementation requirements:

The calculation must run in tested code, not be performed conversationally by the language model. Every result must preserve the equation version, input dates, eligibility decision, and source measurements. Missing inputs must remain missing.

An updated risk estimate is not automatically proof that an intervention caused an equivalent change in actual disease risk.
B. A personal hypothesis model
This maintains competing explanations for observed findings.

Examples include persistent lipid abnormalities, an inherited risk factor, blood-pressure exposure, metabolic factors, or a measurement artifact.

Each hypothesis has supporting evidence, contrary evidence, unresolved questions, and an observation that could change its status.

This component is primarily a structured scientific record. It must not invent numerical probabilities for explanations that have no defensible probability model.
C. A personal response model
This estimates a narrowly defined response, such as a future average blood pressure or the change associated with a specific behavioral comparison.

Its parameters update as prospective observations accumulate.

This is where individual numerical learning occurs. The language model proposes and explains; the statistical model calculates.

The three components must remain distinguishable in the interface. An established population equation, a plausible explanation, and a replicated personal response do not have the same evidentiary status.
4. What “going deeper” should mean
The system should not be rewarded for finding an unusual diagnosis or suggesting an unconventional intervention.

It should be rewarded for resolving uncertainty that matters.

For example, a reported family history of heart attacks should trigger a structured investigation of what is actually known: which relatives, age at the event, age at death, documented diagnosis versus recollection, and associated conditions. Unknown ages must not silently become “premature cardiovascular disease.”

The records should then be examined for relevant patterns and gaps.

Current dyslipidemia guidance already extends beyond LDL cholesterol alone, including Lp(a), selected use of ApoB, other risk-enhancing factors, and selective coronary calcium assessment. The prototype should accurately implement this existing depth before claiming to surpass it. American College of Cardiology

The initial investigation should produce a limited set of evidence-backed questions, such as:

“Were lipid measurements persistently elevated across several years, or does the apparent change coincide with a change in testing method?”

“Is a relevant inherited-risk marker already present in the reports but absent from the current understanding of risk?”

“Is blood-pressure exposure genuinely known, or is the interpretation resting on family history and occasional measurements?”

“Would another measurement change a decision, or merely add detail?”

These are examples of questions, not findings about the participant.

Every proposed test must include a decision statement:

“If the result is A, the next step changes in this way. If it is B, it changes in that way.”

A test that cannot satisfy that requirement should generally rank below one that can.

Initially, rank information value using explicit reasoning about relevance, uncertainty, burden, cost, and actionability. Do not produce an artificial “information gain score” unless an actual quantitative model supports it.
5. Data ingestion must preserve uncertainty
The first engineering priority is a verified longitudinal record.

Support uploaded laboratory reports, structured exports where available, and manual entry. Do not make the first release depend on portal scraping or undocumented vendor integrations.

Preserve the original document and create normalized observations alongside it.

Each observation needs:
Observation
  participant_id
  source_document_id
  source_location
  original_test_name
  normalized_test_name
  original_value_and_unit
  normalized_value_and_unit
  collection_date
  report_date
  specimen_type
  laboratory_and_method_if_known
  reference_range
  relevant_collection_conditions
  extraction_status
  verification_status
  supersedes_observation_id

Unknown fields stay unknown.

The system must distinguish collection date from upload date, reported values from calculated values, and a corrected result from a second independent measurement.
Historical finger-prick results
Keep these as a distinct measurement stream until comparability is established.

Do not discard them merely because they are capillary samples. Research has demonstrated agreement for certain analytes and collection workflows. However, that evidence does not establish interchangeability for every device, laboratory, assay, or historical report. PubMed Central (PMC)

When comparability is uncertain, the interface should show separate series and explain why an apparent trend cannot yet be interpreted confidently.

Do not estimate a laboratory-to-laboratory correction from a few unrelated measurements.

Unit handling also requires explicit rules. For example, Lp(a) mass and molar measurements should not be silently merged using a universal conversion factor. EAS guidance identifies limitations in such conversion. EAS
Verification workflow
Extraction creates candidates, not accepted facts.

Before a value enters a risk calculation or experiment analysis, display it beside the relevant source passage for confirmation. Ambiguous extraction blocks downstream calculation.

Reference ranges and clinical decision thresholds must be stored separately. A laboratory flag is not itself a diagnosis.
6. Application experience
Chat should be a secondary interface. The main product should make the research state inspectable.
Screen    Main purpose
Overview    Current findings, unresolved questions, active forecasts, and changes since the last review.
Records    Source documents, verified measurements, provenance, and unresolved discrepancies.
Risk investigation    Reference risk estimates and competing explanations, with evidence and limitations.
Research queue    Ranked questions and proposed measurements, including what each result could change.
Experiments    Protocols, eligibility, predictions, observations, deviations, and results.
Model performance    Forecast errors, uncertainty, baseline comparisons, and failed hypotheses.
Project notebook    Product decisions, implementation status, validation gaps, and commercialization assumptions.


Every important statement should have an accessible “basis” view.

That view should identify whether the statement comes from a measurement, self-report, published evidence, a statistical estimate, or an untested hypothesis.

The overview must be capable of saying “nothing materially changed.” It should not manufacture a new insight each time it is opened.
7. Technical architecture
I would use a conventional application architecture with separate research and numerical components.
Layer    Initial choice
Interface    Next.js and TypeScript.
Application API    Python with FastAPI and Pydantic schemas.
Persistent data    PostgreSQL.
Original documents    Private file storage behind a storage adapter.
Research execution    A Python worker with a persistent job queue and explicit workflow states.
Statistical modeling    Versioned Python modules; PyMC where Bayesian modeling is justified.
Language-model access    A provider adapter supporting structured outputs and narrowly scoped tools.
Deployment    Containerized local application first, with a path to private cloud deployment.


Next.js provides the application framework; FastAPI’s OpenAPI and schema support can define contracts between the interface, database operations, and research tools. PyMC supports prior and posterior predictive checks for the numerical modeling workflow. These are implementation components, not evidence of clinical validity. Next.js

Start with one production language-model provider. Select it using the project’s evaluation set rather than assuming the most expensive model is best at every task.

Keep the provider replaceable. Personal records, hypotheses, experiment definitions, and fitted statistical models must remain usable after switching providers.

No fine-tuning, dedicated GPU, graph database, or fleet of autonomous agents is required for version one.

The distinguishing work is in data integrity, experimental design, and prospective evaluation, not infrastructure novelty.
Workflow execution
Use explicit states:
Import
  -> extract
  -> validate
  -> human verification
  -> accepted observations

Research
  -> formulate question
  -> retrieve evidence
  -> assess applicability
  -> challenge explanation
  -> publish hypothesis update

Experiment
  -> draft protocol
  -> eligibility and safety review
  -> participant approval
  -> freeze protocol and prediction
  -> collect observations
  -> analyze
  -> score
  -> update model

Jobs need checkpoints, retry limits, cancellation, deduplication, and spending limits.

A failed job must not leave a half-written clinical conclusion in the accepted record.
Tool permissions
The research model may call approved functions to retrieve evidence, inspect verified observations, run established calculations, and draft updates.

It may not execute arbitrary commands against the production database, overwrite observations, change an active protocol, purchase tests, or initiate treatment.

Structured output can enforce a schema, but a schema-conforming answer can still be factually wrong. Semantic validation remains necessary. OpenAI Developers
8. Privacy and development separation
Use synthetic records during development.

AI coding tools should receive synthetic fixtures, redacted error reports, and database schemas, not unrestricted access to the real health-record directory.

Keep production records outside the source repository. Exclude them from ordinary application logs, analytics, crash reports, and screenshots used in development.

For the personal beta, keep persistent records on encrypted local storage with encrypted backups. External model APIs may receive the minimum necessary information through the application’s provider adapter.

This is local storage with external processing, not a fully local system.

For example, OpenAI states that API data is not used for training by default, but default abuse-monitoring retention and endpoint-specific application-state retention can still apply. The implementation must check the controls for the exact endpoints used rather than equating “not used for training” with “not retained.” OpenAI Developers

Public literature searches should use nonidentifying research questions. Names, exact dates of birth, full reports, and raw genomic files should not be sent to public search tools.

Before any remote deployment, require authentication, private document access, secret management, backup restoration tests, and a review of exposed endpoints.
9. Research engine specification
The research engine should maintain an evidence ledger rather than an accumulating collection of summaries.

Each evidence record must preserve the paper identifier, publication date, study type, population, intervention, comparator, endpoint, duration, relevant result, limitations, and retrieval date.

It should record whether full text was reviewed or only an abstract was available.

A proposed explanation should pass three checks.

First: does the cited source support the claim?

Second: is the source applicable to the person and question being considered?

Third: would the claim remain plausible after considering contradictory evidence and simpler explanations?

The output should distinguish evidence of association, evidence about a causal mechanism, evidence that an intervention changes a biomarker, and evidence that it improves clinical outcomes.

These cannot be collapsed into a single confidence score.

The system should also distinguish absence of evidence from evidence against a hypothesis.

Maintain a small active research queue, initially no more than five questions. Additional possibilities remain in a backlog. This limits endless speculative investigation.

An automated reviewer can help identify contradictions and unsupported claims, but agreement between two AI models must never be treated as independent clinical validation.
10. The numerical prediction engine
The first prediction task should be selected after the data inventory, not predetermined from family history.

My default engineering target would be repeated blood-pressure forecasting because it allows frequent prospective observations. The initial objective would be forecasting measured values, not diagnosing hypertension.

The measurement workflow should follow a documented protocol using a validated upper-arm device and consistent technique. AHA guidance includes appropriate cuff fit, quiet rest, and two readings one minute apart. www.heart.org
Start with simple baselines
Implement these before a personalized model:

A recent-average forecast.

A simple time-trend forecast where justified.

A literature-informed expectation for an intervention, when an applicable estimate exists.

The personalized model must compete against these.

An illustrative response model might be:
Observed outcome
  = personal baseline
  + assigned-condition effect
  + prespecified time or period effect
  + a small number of justified covariates
  + measurement variation
  + correlated residual variation

This is a candidate structure, not a model to apply indiscriminately.

Do not fit dozens of predictors because dozens of biomarkers exist. Model complexity must reflect the amount and structure of relevant data.

Sparse historical laboratory panels may support a descriptive timeline but not a reliable personal treatment-response model.
Population evidence as a starting point
Where justified, use published evidence to inform initial estimates, then update them using personal observations.

Document every prior assumption. Do not treat the confidence interval around an average trial effect as though it describes the distribution of individual responses.

Require sensitivity analyses: does the conclusion change substantially when reasonable assumptions change?
Prediction contract
Before the outcome is observed, save:
Prediction
  target_outcome_and_unit
  target_time_window
  protocol_version
  model_version
  training_data_cutoff
  input_snapshot_hash
  point_prediction
  predictive_interval
  baseline_predictions
  assumptions
  scoring_rule
  timestamp

If insufficient evidence exists to generate a defensible prediction, store an explicit abstention.

The language model must not fill an empty prediction field with an intuitive number.
11. Experiment engine
Every experiment must start with an answerable question.

“Improve cardiovascular health” is not an experiment.

“Under specified conditions, does behavioral option A produce a different measured outcome than option B?” can be.

The protocol must define the intervention, comparator, primary outcome, timing, eligibility, measurement procedure, expected effect timing, possible carryover, analysis, missing-data handling, stopping conditions, and what size of change would matter.

Randomized crossover designs are useful only when their assumptions fit the intervention and outcome. Effects that begin slowly or persist across periods can make a simple alternating design inappropriate. N-of-1 methodology explicitly requires attention to onset, carryover, randomization, and analysis. PubMed Central (PMC)
First live experiment
Begin with observation and forecasting before intervention selection.

After measurement quality and eligibility are established, a possible first behavioral comparison could involve the timing of an already-tolerated walking routine versus the usual schedule.

That is an example of a candidate protocol, not a recommendation to start it now. The system must establish a relevant question, appropriate endpoint, plausible observation window, and safety constraints.

It must not escalate intensity, impose sleep deprivation, induce dehydration, or create another harmful exposure merely to obtain a detectable effect.

If no suitable behavioral experiment exists, remain in observation mode. Do not invent one to demonstrate the product.
Protocol integrity
Once an experiment starts, its original protocol and forecast become read-only.

Changes create amendments with timestamps and reasons.

The primary analysis follows the prespecified plan. Later explorations are labeled exploratory. Deviations, missed measurements, illness, and concurrent changes remain visible.

A favorable result must not be rescued by repeatedly changing the endpoint or excluding inconvenient observations.
Scope of learning
The system may learn that a behavior predicts a measured response under the tested conditions.

That does not establish the full biological mechanism, eliminate all confounding, or prove prevention of a future heart attack.

A result can be useful without supporting those larger claims.
12. Validation requirements
Validation should be separated into distinct gates.
Gate A: Record integrity
Build a manually checked test set covering realistic report formats.

Test wrong dates, duplicate reports, corrected results, missing units, unknown specimen types, changed reference ranges, conflicting measurements, and ambiguous extraction.

For the personal pilot, every measurement used in a calculation must have been checked against its source.

A release fails if unresolved extraction errors can enter a risk calculation silently.
Gate B: Computational correctness
Test risk equations against authoritative reference outputs and boundary cases.

Test statistical routines against simulated datasets where the generating process is known, including no effect, known effect, missingness, serial correlation, and carryover.

Simulation establishes properties of the implementation under specified assumptions. It does not validate the participant’s biology.
Gate C: Prospective forecasting
Evaluate predictions on observations unavailable when the predictions were saved.

Report absolute error, prediction-interval performance, and comparison with simple baselines. Evaluate interval width as well as coverage so that extremely broad intervals are not mistaken for useful accuracy.

Use time-ordered evaluation. Overlapping forecasts and repeated measurements must not be counted as independent evidence of performance.

A small pilot can identify failures and generate preliminary evidence. It cannot establish stable calibration from a handful of forecasts.
Gate D: Personal-response learning
Assess whether repeated, appropriately designed comparisons produce reasonably consistent estimates.

Report uncertainty, protocol deviations, and sensitivity to modeling assumptions.

An inconclusive result remains inconclusive.
Gate E: Practical utility
Measure whether the system reduces unresolved discrepancies, improves the selection of useful questions, decreases unnecessary work, or produces forecasts that inform a defined decision.

Do not use the number of hypotheses, papers retrieved, or tests ordered as success metrics.

Clinical correctness of interpretation remains a separate limitation until qualified review is available.
13. Comparison with a general AI
The prototype must be evaluated against more than an empty chat window.

Use three comparison conditions:
Comparison    Purpose
Structured records plus simple numerical baselines    Determines whether additional modeling improves forecasting.
The same language model given the same records and evidence, without the research workflow    Tests the contribution of persistent hypotheses, protocol control, and explicit models.
The complete prototype    Measures the combined process.


All conditions should have the same information cutoff.

For predictions, judge results against later observations. For research output, use a predefined rubric covering factual accuracy, citation support, acknowledgment of uncertainty, and whether a proposed measurement changes a decision.

Without expert review, the prototype can evaluate source fidelity and forecast accuracy more credibly than the clinical merit of every explanation. It should state that limitation.

The product earns its additional complexity only when the structured process produces measurable benefits.
14. Build sequence for AI coding tools
Build in small, testable increments. Do not give an agent the entire brief and accept a polished demonstration as completion.
Milestone    Deliverable    Acceptance condition
1. Foundation    Local application, database migrations, synthetic fixtures, authentication, and backup process.    A clean installation works; backup restoration succeeds.
2. Verified records    Upload, extraction, source comparison, corrections, and longitudinal display.    A result can be traced back to its source; ambiguous values cannot enter calculations.
3. Risk investigation    Eligibility-aware reference calculation, hypothesis records, and evidence ledger.    Calculations match reference cases; claims expose their evidence and status.
4. Observation workflow    Measurement entry, quality flags, scheduled forecasts, and baseline models.    Forecasts are saved before outcomes and cannot be silently rewritten.
5. Experiment workflow    Protocol state machine, approvals, amendments, outcome collection, and analysis.    Simulated experiments exercise the full lifecycle, including failure and cancellation.
6. Personal beta    Real records and a prospective observation period.    The system works without developer intervention for ordinary tasks.
7. Evaluation    Performance report, unresolved failures, and exportable research record.    Results are reported against baselines, including lack of improvement.


Each milestone requires automated tests, an end-to-end demonstration, known limitations, and a rollback path.

Acceptance criteria should be fixed before implementation. The coding agent must not weaken them to make its own work pass.

Maintain a small set of withheld tests that are not used to optimize the implementation.
Repository structure
AGENTS.md
docs/
  product-brief.md
  architecture.md
  safety-boundaries.md
  validation-plan.md
  decisions.md
  current-state.md
  commercial-hypotheses.md

apps/
  web/

services/
  api/
  worker/

packages/
  schemas/
  risk-models/
  response-models/
  evidence-tools/

tests/
  ingestion/
  calculations/
  forecasting/
  safety/
  end-to-end/

fixtures/
  synthetic/

The initial development instruction should be:

“Build the verified-record workflow and its tests first. Do not implement treatment recommendations or personalized forecasts until their prerequisites and evaluation harness exist.”
15. Personal beta procedure
Run the beta as a sequence of evidence-gathering stages, not a product launch.

First, inventory and verify the existing records. Establish what is known, what is self-reported, and what cannot be reconciled.

Second, generate the initial risk investigation. Review whether the system asks consequential questions rather than merely producing a longer version of generic prevention advice.

Third, test the measurement workflow without deliberately changing behavior. Evaluate burden, missingness, device consistency, and prospective forecasts.

Fourth, select at most one eligible behavioral comparison. The protocol should be determined by the question and evidence, not by a desire to produce a result quickly.

Fifth, evaluate and, where appropriate, replicate. Produce an explicit report of what was learned and what remains unsupported.

The participant’s role is source verification, measurement collection, approval of permitted actions, and usability testing. That role does not substitute for clinical or statistical expertise.

Software progress and biological evidence will accumulate on different schedules. A functioning interface can be complete while its personal-response claims remain unvalidated.
16. Genetics and advanced testing
Do not make genome sequencing a prerequisite.

The architecture should accommodate future genetic evidence, but version one should first determine which important questions remain unresolved after existing records and ordinary measurements are reviewed.

A later genetics module would require explicit handling of assay quality, genome build, variant identity, clinical interpretation, conflicting classifications, and confirmation requirements.

ClinVar exposes differing levels of review and conflicting interpretations. A variant match alone is not equivalent to an established personal diagnosis. NCBI

Polygenic scores also require attention to the population in which they were developed and evaluated, their incremental predictive contribution, and their clinical applicability. They should not be treated as a universal personalized explanation of disease. PubMed Central (PMC)

Genomic findings should enter the same evidence framework as everything else: what is observed, what it may imply, what remains uncertain, and whether it changes a decision.

The system must be willing to conclude that another test would add little.
17. The persistent product “second brain”
Maintain a product notebook separate from the medical research record.

It should preserve the current objective, architectural decisions, rejected approaches, implementation status, validation evidence, unresolved risks, and commercial assumptions.

After each milestone, the development agent proposes updates. Accepted decisions become versioned records.

After each experiment, it should create two separate summaries.

The scientific summary explains what the result supports about the measured outcome.

The product summary explains what the result supports about the software.

For example:

“The measurement workflow was completed reliably” is product evidence.

“The intervention had a detectable effect” is scientific evidence.

“The prototype can prevent cardiovascular events” is not supported by either finding alone.

This separation prevents enthusiasm about the business from influencing the interpretation of medical results.
18. Commercialization path
The eventual product would be the system that builds and maintains personal research models, not one participant’s fitted model sold as applicable to everyone.

The first commercial hypothesis I would test is a clinician-supported workflow for longitudinal cardiovascular investigation and response monitoring.

That is a product hypothesis, not a settled business model.

Before expansion, establish whether other people can complete the measurement workflow, whether clinicians find the output useful, how much review it requires, whether predictions generalize, and whether the process improves a defined outcome compared with a simpler alternative.

Record software costs, model usage, participant burden, and review effort during the pilot. Budget is currently unspecified, so paid services must have configurable per-job and monthly limits rather than assumed unlimited usage.

No multi-user training on personal records should occur by default. Secondary use requires its own consent, governance, and evaluation plan.

Commercial claims will affect regulatory obligations. FDA’s current clinical decision-support guidance distinguishes functions based on intended use; describing disease-directed software as a “research assistant” does not itself establish that it is outside device oversight. Consumer health products may also have FTC obligations even when HIPAA does not apply. U.S. Food and Drug Administration

Clinical, statistical, security, and regulatory review should therefore become explicit expansion gates rather than assumed future details.
19. Definition of success
The prototype succeeds as an engineering project when it can ingest records accurately, maintain an inspectable research state, preserve prospective predictions, run reproducible analyses, and expose its failures.

It succeeds as a personal research project when it resolves a consequential uncertainty or produces a repeatable, bounded understanding of a response that was not established beforehand.

It earns a claim of predictive improvement only when it outperforms the predefined alternatives on prospective observations.

It does not fail merely because the eventual prevention options remain conventional. It fails if it invents a more personalized story without producing better evidence.

The first complete deliverable should be a record that says:

“This was the question. These were the competing explanations. This was the prediction made before the measurement. This is what happened. This is what changed in the model, and this is what still cannot be concluded.”
