"""ClinicalRecordReader: an optional, pluggable way to locate the observations a research
question depends on.

A reader returns observation IDs only. Values, units and dates are always taken by ordinary code
from the snapshot by those IDs, and every comparison or calculation stays deterministic. The
default reader matches by normalized test key or by the test name as written. A specialist reader
(for example a clinical model under evaluation) can implement the same protocol; it is never
installed by default and must be compared with the default reader on the same inputs with
`compare_readers` before it is used.
"""

import time
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ReadTarget:
    role: str  # e.g. "ldl_particle_number"
    keys: tuple[str, ...] = ()  # normalized test keys
    names: tuple[str, ...] = ()  # test names as written, lower case, exact match


@dataclass
class ReadResult:
    reader: str
    found: dict[str, list[str]]  # role -> observation IDs
    abstained: list[str] = field(default_factory=list)  # roles the reader declined to resolve
    errors: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    cost_usd: float = 0.0


class ClinicalRecordReader(Protocol):
    name: str

    def read(self, observations: list[dict], targets: list[ReadTarget]) -> ReadResult: ...


class DeterministicRecordReader:
    name = "deterministic-v1"

    def read(self, observations: list[dict], targets: list[ReadTarget]) -> ReadResult:
        start = time.perf_counter()
        found: dict[str, list[str]] = {}
        for t in targets:
            found[t.role] = [
                o["observation_id"] for o in observations
                if o["key"] in t.keys or o["test_as_written"].strip().lower() in t.names
            ]
        return ReadResult(self.name, found, latency_ms=(time.perf_counter() - start) * 1000)


def compare_readers(baseline: ClinicalRecordReader, candidate: ClinicalRecordReader,
                    observations: list[dict], targets: list[ReadTarget]) -> dict:
    """Same inputs to both readers; report agreement, errors, abstentions, latency and cost."""
    b = baseline.read(observations, targets)
    try:
        c = candidate.read(observations, targets)
    except Exception as exc:  # a failing candidate is a result, not a crash
        c = ReadResult(getattr(candidate, "name", "candidate"), {}, errors=[type(exc).__name__])
    roles = []
    for t in targets:
        bs, cs = set(b.found.get(t.role, [])), set(c.found.get(t.role, []))
        roles.append({"role": t.role, "agree": bs == cs, "baseline_only": sorted(bs - cs),
                      "candidate_only": sorted(cs - bs), "candidate_abstained": t.role in c.abstained})
    return {
        "baseline": b.reader, "candidate": c.reader, "roles": roles,
        "agreement": sum(r["agree"] for r in roles), "of": len(roles),
        "errors": {"baseline": b.errors, "candidate": c.errors},
        "abstentions": {"baseline": b.abstained, "candidate": c.abstained},
        "latency_ms": {"baseline": round(b.latency_ms, 3), "candidate": round(c.latency_ms, 3)},
        "cost_usd": {"baseline": b.cost_usd, "candidate": c.cost_usd},
    }
