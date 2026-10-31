"""Evidence-record format shared by the public notebook and the future research layer.

Records live as JSON under research/ (public, no personal data). They describe published
evidence only. Personal applicability is a separate, explicit field that stays "not_assessed"
until verified personal observations exist and an assessment is recorded.

Structural rules are enforced by these Pydantic models; cross-record and source-fidelity rules
are enforced by evidence_tools.validate.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Slug = str


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Citation(Strict):
    authors: list[str] = Field(min_length=1)
    title: str
    journal: str
    year: int
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    doi: str
    pmid: str
    pmcid: str | None = None
    url: str

    @field_validator("doi")
    @classmethod
    def _doi(cls, v: str) -> str:
        if not re.fullmatch(r"10\.\d{4,9}/\S+", v):
            raise ValueError("DOI must look like 10.xxxx/yyyy")
        return v

    @field_validator("pmid")
    @classmethod
    def _pmid(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("PMID must be digits")
        return v


class Access(Strict):
    full_text_reviewed: bool
    full_text_source: str | None = None  # e.g. "PubMed Central XML (efetch)"
    license: str | None = None
    supplement_reviewed: bool
    retrieved_on: date
    abstract_only_note: str | None = None

    @model_validator(mode="after")
    def _abstract_only(self) -> Access:
        if not self.full_text_reviewed and not self.abstract_only_note:
            raise ValueError("abstract-only records must explain the limitation in abstract_only_note")
        return self


StudyDesign = Literal[
    "prospective_cohort",
    "pooled_prospective_cohorts",
    "randomized_repeated_crossover_trial",
    "randomized_parallel_trial",
    "mendelian_randomization",
    "meta_analysis",
    "laboratory_method_validation",  # analytical performance of an assay; no outcomes
    "trial_secondary_analysis",  # post hoc analysis within a randomized trial's participants
    "narrative_review",  # synthesis without new data; claims are the authors' statements
]
RANDOMIZED_DESIGNS = {"randomized_repeated_crossover_trial", "randomized_parallel_trial"}


class Study(Strict):
    design: StudyDesign
    design_detail: str
    evidence_type: Literal["observational_association", "randomized_comparison", "method_characteristics",
                           "narrative_synthesis"]
    population: str
    setting: str
    sample_size: int | None  # None when the source does not report one (reviews; abstract-only method papers)
    exposure_or_intervention: str
    comparator: str
    outcomes: list[str] = Field(min_length=1)
    follow_up: str

    @model_validator(mode="after")
    def _type_matches_design(self) -> Study:
        randomized = self.design in RANDOMIZED_DESIGNS
        if randomized != (self.evidence_type == "randomized_comparison"):
            raise ValueError("evidence_type must be randomized_comparison exactly when the design is randomized")
        return self


class SourceLocation(Strict):
    section: str  # e.g. "Results", "Abstract", "Table 2"
    element: str  # e.g. "Table 2, row 'apoB residual'", "paragraph 'Associations on follow-up'"
    quote: str = Field(min_length=10)  # verbatim excerpt from the full text that contains the value(s)


class Derivation(Strict):
    """Our own calculation from reported inputs. Never presented as a reported result."""

    method: Literal["divide_by_sqrt_2pi", "difference", "range_width"]
    inputs: list[str] = Field(min_length=1)  # claim ids (or "claim_id.lower" / "claim_id.upper")
    explanation: str


ClaimKind = Literal[
    "descriptive",  # sample characteristics, distributions
    "association",  # observational association; not causal
    "randomized_effect",  # effect estimated from a randomized comparison
    "model_estimate",  # a quantity that holds only if a fitted model is true
]
Scale = Literal["absolute", "relative", "descriptive"]


class Claim(Strict):
    id: Slug
    statement: str
    kind: ClaimKind
    measure: str  # hazard_ratio, event_rate, range, mean_difference, sd, regression_slope, ...
    scale: Scale
    value: float | None  # None only for measure "range": the paper reports bounds, not a centre
    lower: float | None = None
    upper: float | None = None
    decimals: int = Field(ge=0, le=6)  # decimals as reported in the source; used for display and checks
    unit: str  # "ratio" for unitless ratios; "unit not stated" when the paper does not state one
    interval: str | None = None  # e.g. "95% CI", "approximately 95% of observations (mean ± 2 SD)"
    comparison: str
    population: str
    time_horizon: str | None = None
    provenance: Literal["reported", "derived"]
    source_location: SourceLocation | None = None
    derivation: Derivation | None = None

    @model_validator(mode="after")
    def _provenance(self) -> Claim:
        if self.provenance == "reported" and (self.source_location is None or self.derivation is not None):
            raise ValueError(f"{self.id}: reported claims need a source_location and no derivation")
        if self.provenance == "derived" and self.derivation is None:
            raise ValueError(f"{self.id}: derived claims need a derivation")
        for name in ("value", "lower", "upper"):
            v = getattr(self, name)
            if v is not None and round(v, self.decimals) != v:
                raise ValueError(f"{self.id}: {name}={v} has more precision than decimals={self.decimals}")
        if self.value is None and (self.measure != "range" or self.lower is None):
            raise ValueError(f"{self.id}: value may be omitted only for a range with bounds")
        if (self.lower is None) != (self.upper is None):
            raise ValueError(f"{self.id}: give both lower and upper, or neither")
        if self.lower is not None and self.interval is None:
            raise ValueError(f"{self.id}: an interval needs an interval description")
        return self


class Limitation(Strict):
    text: str
    source: Literal["stated_by_authors", "identified_in_review"]


class Discrepancy(Strict):
    description: str
    locations: list[str] = Field(min_length=1)
    handling: str


class Review(Strict):
    status: Literal["draft", "source_verified", "reviewed"]
    verified_by: str
    verified_on: date
    method: str
    independent_review: bool = False  # True only for a qualified human reviewer outside this project


class Publication(Strict):
    # "published" is intentionally not allowed: nothing is published automatically.
    status: Literal["unpublished", "local_notebook_only"]


class EvidenceRecord(Strict):
    schema_version: Literal[1] = 1
    id: Slug
    short_title: str
    citation: Citation
    access: Access
    study: Study
    claims: list[Claim] = Field(min_length=1)
    findings_summary: str  # what the study found, in plain technical language
    limitations: list[Limitation] = Field(min_length=1)
    applicability_constraints: list[str] = Field(min_length=1)
    discrepancies: list[Discrepancy] = []
    interpretation: str  # our reading; kept separate from what the paper reports
    review: Review
    publication: Publication

    @model_validator(mode="after")
    def _claims(self) -> EvidenceRecord:
        ids = [c.id for c in self.claims]
        if len(ids) != len(set(ids)):
            raise ValueError("claim ids must be unique")
        if self.study.evidence_type != "randomized_comparison":
            bad = [c.id for c in self.claims if c.kind == "randomized_effect"]
            if bad:
                raise ValueError(f"{self.study.evidence_type} study cannot carry randomized_effect claims: {bad}")
        if self.review.status != "draft" and not self.access.full_text_reviewed:
            if not any("abstract" in l.text.lower() for l in self.limitations):
                raise ValueError("verified abstract-only records must list the abstract-only limitation")
        return self


class PersonalObservation(Strict):
    observation: str
    why: str
    currently_available: Literal["no", "unknown", "not_imported"]


class DecisionRelevance(Strict):
    if_observed: str
    would_change: str


class Applicability(Strict):
    status: Literal["not_assessed", "assessed"]
    reason: str


class ResearchQuestion(Strict):
    schema_version: Literal[1] = 1
    id: Slug
    question: str
    evidence_ids: list[Slug] = Field(min_length=1)
    motivation: str  # why the evidence motivates the question
    project_connection: str  # specific connection to this project's records/workflow
    required_personal_observations: list[PersonalObservation] = Field(min_length=1)
    decision_relevance: list[DecisionRelevance] = Field(min_length=1)
    what_remains_uncertain: list[str] = Field(min_length=1)
    what_cannot_be_concluded: list[str] = Field(min_length=1)
    personal_applicability: Applicability
    chart_ids: list[Slug] = []


class ChartRowSpec(Strict):
    row_id: str
    claim_id: Slug
    group: str  # x-axis category
    label: str  # short label for the mark
    series: str  # legend entry


class ReferenceLine(Strict):
    value: float
    label: str


class ChartSpec(Strict):
    schema_version: Literal[1] = 1
    id: Slug
    evidence_id: Slug
    rows: list[ChartRowSpec] = Field(min_length=1)
    title: str
    chart_type: Literal["range_bars", "paired_bars", "interval_points"]
    data_file: str  # CSV under research/charts/
    x_label: str
    y_label: str
    caption: str
    reading_note: str  # how to read the chart correctly (absolute vs relative, population, horizon)
    reference_line: ReferenceLine | None = None


CHART_COLUMNS = (
    "row_id", "claim_id", "group", "label", "series", "value", "lower", "upper", "decimals", "unit",
    "provenance", "source_section", "source_element",
)


class BuildResult(Strict):
    check: str
    result: str
    scope: str  # what the check does and does not establish


class BuildNote(Strict):
    """A product/software entry. Kept separate from scientific evidence (brief §17)."""

    schema_version: Literal[1] = 1
    id: Slug
    date: date
    title: str
    kind: Literal["software_build"]
    summary: str
    results: list[BuildResult] = Field(min_length=1)
    what_this_is_not: list[str] = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)
    next_steps: list[str] = []

    @model_validator(mode="after")
    def _internal(self) -> BuildNote:
        text = " ".join(self.what_this_is_not).lower()
        if "clinical validation" not in text or "external review" not in text:
            raise ValueError("build notes must state they are not clinical validation or external review")
        return self
