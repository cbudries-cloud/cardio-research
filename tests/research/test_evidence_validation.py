"""The evidence format and validator: the real corpus passes, and each rule can fail."""

import copy
import json
import os
import shutil
from pathlib import Path

import pytest

from evidence_tools import validate
from evidence_tools.schema import EvidenceRecord, ResearchQuestion

RESEARCH = Path(os.environ.get("CARDIO_RESEARCH_DIR", "/research"))
CACHE = os.environ.get("CARDIO_SOURCE_CACHE")


def test_corpus_is_valid():
    corpus, errors = validate.load(RESEARCH)
    errors += validate.check(corpus)
    assert errors == []
    assert corpus.evidence and corpus.questions and corpus.charts


@pytest.mark.skipif(not CACHE, reason="full-text cache is kept outside the repository")
def test_quotes_are_verbatim_in_full_text():
    corpus, errors = validate.load(RESEARCH)
    assert validate.check(corpus, Path(CACHE)) == []


def test_every_question_is_not_assessed_personally():
    corpus, _ = validate.load(RESEARCH)
    assert all(q.personal_applicability.status == "not_assessed" for q in corpus.questions.values())


@pytest.fixture
def workdir(tmp_path):
    dst = tmp_path / "research"
    shutil.copytree(RESEARCH, dst)
    return dst


def _first_evidence(root: Path) -> tuple[Path, dict]:
    path = sorted((root / "evidence").glob("*.json"))[0]
    return path, json.loads(path.read_text())


def _errors(root: Path) -> list[str]:
    corpus, errors = validate.load(root)
    return errors + validate.check(corpus)


def test_changed_value_not_in_quote_fails(workdir):
    path, ev = _first_evidence(workdir)
    claim = next(c for c in ev["claims"] if c["provenance"] == "reported" and c.get("value") is not None)
    claim["value"] = claim["value"] + 0.37
    path.write_text(json.dumps(ev))
    errors = _errors(workdir)
    assert any("does not appear in the source quote" in e or "more precision than decimals" in e for e in errors)


def test_chart_row_drifting_from_claim_fails(workdir):
    data = next((workdir / "charts").glob("*.csv"))
    lines = data.read_text().splitlines()
    header, first = lines[0].split(","), lines[1].split(",")
    i = header.index("value") if first[header.index("value")] else header.index("lower")
    first[i] = str(float(first[i]) + 1)
    data.write_text("\n".join([lines[0], ",".join(first), *lines[2:]]) + "\n")
    assert any("!= claim" in e for e in _errors(workdir))


def test_wrong_derivation_fails(workdir):
    for path in (workdir / "evidence").glob("*.json"):
        ev = json.loads(path.read_text())
        derived = [c for c in ev["claims"] if c["provenance"] == "derived"]
        if derived:
            derived[0]["value"] += 1
            path.write_text(json.dumps(ev))
            break
    else:
        pytest.skip("no derived claims")
    assert any("recomputed" in e for e in _errors(workdir))


def test_personal_applicability_cannot_be_assessed_yet(workdir):
    path = next((workdir / "questions").glob("*.json"))
    q = json.loads(path.read_text())
    q["personal_applicability"]["status"] = "assessed"
    path.write_text(json.dumps(q))
    assert any("not_assessed" in e for e in _errors(workdir))


def _base_record() -> dict:
    return json.loads((RESEARCH / "evidence" / "sniderman-2024-apob-discordance.json").read_text())


def test_publication_status_published_is_rejected():
    ev = _base_record()
    ev["publication"]["status"] = "published"
    with pytest.raises(Exception):
        EvidenceRecord.model_validate(ev)


def test_observational_study_cannot_claim_randomized_effect():
    ev = _base_record()
    assert ev["study"]["evidence_type"] == "observational_association"
    ev["claims"][0]["kind"] = "randomized_effect"
    with pytest.raises(Exception, match="randomized_effect"):
        EvidenceRecord.model_validate(ev)


def test_design_and_evidence_type_must_agree():
    ev = _base_record()
    ev["study"]["evidence_type"] = "randomized_comparison"
    with pytest.raises(Exception, match="evidence_type"):
        EvidenceRecord.model_validate(ev)


def test_reported_claim_needs_source_location():
    ev = _base_record()
    ev["claims"][0]["source_location"] = None
    with pytest.raises(Exception, match="source_location"):
        EvidenceRecord.model_validate(ev)


def test_abstract_only_must_be_declared():
    ev = _base_record()
    ev["access"]["full_text_reviewed"] = False
    ev["access"]["abstract_only_note"] = None
    with pytest.raises(Exception, match="abstract"):
        EvidenceRecord.model_validate(ev)


def test_quote_not_in_cache_fails(tmp_path, workdir):
    cache = tmp_path / "cache"
    cache.mkdir()
    for path in (workdir / "evidence").glob("*.json"):
        (cache / path.name.replace(".json", ".txt")).write_text("unrelated text")
    corpus, _ = validate.load(workdir)
    assert any("not found verbatim" in e for e in validate.check(corpus, cache))


def test_number_forms():
    assert validate.number_in_text(0.85, "HR .85 (95% CI")
    assert validate.number_in_text(293876, "A sample of 293 876 adults")
    assert validate.number_in_text(-2.1, "−2.1 (−3.3 to –1.0)")
    assert not validate.number_in_text(1.06, "HR 1.065")
    assert not validate.number_in_text(4.0, "14.0")


def test_reported_precision_must_match_source(workdir):
    """A value shown at a precision the paper did not report (e.g. 4.0 written as 4) fails."""
    path, ev = _first_evidence(workdir)
    claim = next(c for c in ev["claims"] if c["provenance"] == "reported" and c.get("decimals", 0) >= 1
                 and c.get("value") is not None)
    claim["decimals"] = claim["decimals"] + 1
    path.write_text(json.dumps(ev))
    assert any("does not appear in the source quote" in e for e in _errors(workdir))


def test_chart_spec_row_pointing_to_missing_claim_fails(workdir):
    spec_path = next((workdir / "charts").glob("*.json"))
    spec = json.loads(spec_path.read_text())
    spec["rows"][0]["claim_id"] = "no-such-claim"
    spec_path.write_text(json.dumps(spec))
    assert any("unknown claim" in e for e in _errors(workdir))


def test_derived_claims_are_never_shown_as_reported():
    corpus, _ = validate.load(RESEARCH)
    for ev in corpus.evidence.values():
        for c in ev.claims:
            if c.provenance == "derived":
                assert c.source_location is None and "our calculation" in c.derivation.explanation.lower() or \
                    "computed" in c.derivation.explanation.lower()


def test_method_and_review_records_cannot_claim_randomized_effect():
    ev = json.loads((RESEARCH / "evidence" / "caulfield-2008-ion-mobility.json").read_text())
    ev["claims"][0]["kind"] = "randomized_effect"
    with pytest.raises(Exception, match="randomized_effect"):
        EvidenceRecord.model_validate(ev)


def test_small_whole_numbers_may_be_written_as_words():
    assert validate.formatted_in_text(1, 0, "One molecule of apo B 100 encircles VLDL, LDL, and Lp(a) particles.")
    assert not validate.formatted_in_text(2, 0, "One molecule of apo B 100 encircles VLDL, LDL, and Lp(a) particles.")
    assert not validate.formatted_in_text(1.5, 1, "one and a half")
