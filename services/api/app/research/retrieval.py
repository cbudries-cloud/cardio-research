"""Evidence retrieval for a research question.

Two sources:
1. The verified evidence ledger (research/evidence), by record ID. Always used.
2. Optional public PubMed search (NCBI E-utilities), only if CARDIO_PUBLIC_SEARCH=pubmed. Queries
   are fixed, non-identifying research questions defined in code; no personal value, date, name or
   report text is ever placed in a query. Off by default: calling NCBI from the application would
   add an external service, which needs the participant's approval.
Search hits are candidates for the ledger, never evidence by themselves: a hit becomes citable only
after it is verified into a ledger record.
"""

import json
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

# Each query is a constant. Tests assert that none contains a digit or anything from a record.
QUERIES = {
    "apob_vs_ldlp_discordance": "apolipoprotein B LDL particle number discordance",
    "ldlp_method_agreement": "LDL particle number ion mobility nuclear magnetic resonance comparison",
}


@dataclass
class Retrieval:
    ledger_records: list[str]
    missing_records: list[str]
    search: dict = field(default_factory=dict)  # query id -> {"status", "pmids", "titles"}
    blockers: list[str] = field(default_factory=list)


def _pubmed(query: str) -> dict:
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    q = urllib.parse.quote(query)
    with urllib.request.urlopen(f"{base}esearch.fcgi?db=pubmed&term={q}&retmax=8&sort=relevance&retmode=json",
                                timeout=20) as r:
        ids = json.loads(r.read())["esearchresult"]["idlist"]
    time.sleep(0.4)
    titles = {}
    if ids:
        with urllib.request.urlopen(f"{base}esummary.fcgi?db=pubmed&id={','.join(ids)}&retmode=json", timeout=20) as r:
            res = json.loads(r.read())["result"]
        titles = {i: res[i]["title"] for i in res.get("uids", [])}
    return {"status": "live", "pmids": ids, "titles": titles}


def retrieve(ledger: dict, record_ids: list[str], query_ids: list[str], env: dict | None = None) -> Retrieval:
    env = os.environ if env is None else env
    out = Retrieval([r for r in record_ids if r in ledger], [r for r in record_ids if r not in ledger])
    if env.get("CARDIO_PUBLIC_SEARCH") != "pubmed":
        out.blockers.append("In-app public search is off (CARDIO_PUBLIC_SEARCH is not 'pubmed'); enabling it adds "
                            "NCBI as an external service and needs approval. Evidence comes from the verified ledger.")
        out.search = {q: {"status": "not_run", "pmids": [], "titles": {}} for q in query_ids}
        return out
    for q in query_ids:
        query = QUERIES[q]
        assert not re.search(r"\d", query), "public queries must not contain numbers"
        try:
            out.search[q] = _pubmed(query)
        except Exception as exc:
            out.search[q] = {"status": f"failed: {type(exc).__name__}", "pmids": [], "titles": {}}
    return out


# --- Literature search for investigations (D-057) -------------------------------------------
# Separate from the fixed ledger retrieval above. On when CARDIO_LITERATURE_SEARCH=pubmed. Queries are constants
# chosen by research priority in partner.py; nothing from a record is ever placed in one. Hits are abstracts only:
# candidates the model may weigh as unverified, never ledger evidence.

ABSTRACT_CHARS = 2400


def _text(el) -> str:
    return "".join(el.itertext()).strip() if el is not None else ""


def _abstracts(pmids: list[str]) -> list[dict]:
    import xml.etree.ElementTree as ET

    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    with urllib.request.urlopen(f"{base}efetch.fcgi?db=pubmed&id={','.join(pmids)}&retmode=xml", timeout=30) as r:
        root = ET.fromstring(r.read())
    out = []
    for art in root.iter("PubmedArticle"):
        pmid = _text(art.find(".//MedlineCitation/PMID"))
        abstract = " ".join(_text(a) for a in art.findall(".//Abstract/AbstractText"))
        if not abstract:
            continue
        out.append({"pmid": pmid, "title": _text(art.find(".//ArticleTitle")),
                    "journal": _text(art.find(".//Journal/Title")), "year": _text(art.find(".//JournalIssue/PubDate/Year")),
                    "abstract": abstract[:ABSTRACT_CHARS] + (" [truncated]" if len(abstract) > ABSTRACT_CHARS else ""),
                    "status": "abstract only, found by a public search; not verified into the evidence ledger"})
    return out


def search_literature(queries: dict[str, str], env: dict | None = None, per_query: int = 4) -> dict:
    env = os.environ if env is None else env
    for q in queries.values():
        assert not re.search(r"\d", q), "public queries must not contain numbers"
    if env.get("CARDIO_LITERATURE_SEARCH") != "pubmed":
        return {"status": "off", "queries": list(queries.values()), "candidates": []}
    pmids: list[str] = []
    try:
        for q in queries.values():
            ids = _pubmed(q)["pmids"][:per_query]
            pmids += [i for i in ids if i not in pmids]
            time.sleep(0.4)
        candidates = _abstracts(pmids) if pmids else []
    except Exception as exc:
        return {"status": f"failed: {type(exc).__name__}", "queries": list(queries.values()), "candidates": []}
    return {"status": "live", "queries": list(queries.values()), "candidates": candidates}
