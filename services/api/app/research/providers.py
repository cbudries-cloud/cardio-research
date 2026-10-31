"""Research model providers.

Two uses, kept apart:

1. Snapshots. The runtime's narrative step always uses the MockProvider: deterministic text
   assembled from the structured result, labelled `mock`. Creating a snapshot never calls a model.
2. Live runs (`app/research/live_run.py`). A live provider is called only for one prepared run
   whose exact request the participant approved on the approval screen. There is no standing
   approval setting: approval is a per-run database record bound to the payload hash, provider,
   model and endpoint, and it is consumed by that run.

The live provider is an adapter (`LiveProvider` protocol); Anthropic is the first one. Numerical
retrieval and calculations never go to a provider.

Configuration (environment of the api container):
  CARDIO_RESEARCH_PROVIDER    anthropic (the only live adapter so far)
  CARDIO_LLM_MODEL            model identifier, e.g. claude-opus-5-5
  CARDIO_LLM_API_KEY_FILE     path of a file holding the API key (default
                              /run/cardio-secrets/anthropic_api_key, a read-only mount of
                              ~/.cardio-secrets). The key is read when a call is made, never
                              returned by the API, never logged.
"""

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

DEFAULT_KEY_FILE = "/run/cardio-secrets/anthropic_api_key"


@dataclass
class ProviderResult:
    provider: str
    execution: str  # "mock" | "live" | "blocked"
    text: str | None
    model: str | None = None
    latency_ms: float = 0.0
    cost_usd: float | None = 0.0
    error: str | None = None
    blockers: list[str] = field(default_factory=list)


class MockProvider:
    name = "mock"

    def complete(self, step: str, payload: dict) -> ProviderResult:
        start = time.perf_counter()
        text = payload.get("deterministic_summary") or ""
        return ProviderResult(self.name, "mock", f"[MOCK: no model was called] {text}",
                              latency_ms=(time.perf_counter() - start) * 1000)


@dataclass
class LiveResponse:
    status: str  # "succeeded" | "failed"
    body: dict | None
    latency_ms: float
    error: str | None = None  # exception class or HTTP status and API error type; never content


class LiveProvider(Protocol):
    name: str
    endpoint: str
    model: str | None

    def blockers(self) -> list[str]: ...
    def build_request(self, *, system: str, user_content: str, output_schema: dict, max_tokens: int,
                      effort: str) -> dict: ...
    def send(self, request_body: dict, timeout_s: int) -> LiveResponse: ...


# Prices in USD per million tokens, from https://platform.claude.com/docs/en/about-claude/pricing
# (retrieved 2026-10-26). Global routing; no inference_geo multiplier applies because none is requested.
ANTHROPIC_PRICES = {
    "claude-opus-5-5": {"input": 4.00, "output": 20.00},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00},
}
# Data handling as stated in Anthropic's documentation (retrieved 2026-10-26). Shown on the approval
# screen; organization-level settings (ZDR, HIPAA readiness) are not visible to this application.
ANTHROPIC_DATA_HANDLING = [
    {"setting": "Standard API retention",
     "text": "For Anthropic API users, inputs and outputs are deleted on Anthropic's backend within 30 days of receipt "
             "or generation, unless otherwise agreed (for example a zero data retention agreement).",
     "source": "https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data"},
    {"setting": "Usage Policy flags",
     "text": "Inputs and outputs flagged for Usage Policy violations may be retained for up to 2 years, and trust and "
             "safety classification scores for up to 7 years.",
     "source": "https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data"},
    {"setting": "Model training",
     "text": "Inputs and outputs from commercial products (including the API) are not used for training, unless you "
             "send feedback or otherwise opt in.",
     "source": "https://privacy.claude.com/en/articles/7996868-is-my-data-used-for-model-training"},
    {"setting": "Structured outputs",
     "text": "The JSON schema (not the prompt or output) is compiled and cached for up to 24 hours. The schema used here "
             "is fixed by this application and contains no personal data.",
     "source": "https://platform.claude.com/docs/en/manage-claude/api-and-data-retention"},
    {"setting": "Zero data retention / HIPAA readiness",
     "text": "Not verified by this application. They are organization-level arrangements in the Claude Console "
             "(platform.claude.com/settings/privacy). Unless you have enabled one for the organization that owns the "
             "key, the standard 30-day retention above applies.",
     "source": "https://platform.claude.com/docs/en/manage-claude/api-and-data-retention"},
    {"setting": "Model retention requirement",
     "text": "Claude Opus 5.5 is not a designated Covered Model (those are Fable/Mythos 5 and 5.1, which require "
             "30-day retention).",
     "source": "https://platform.claude.com/docs/en/manage-claude/api-and-data-retention"},
]


class AnthropicProvider:
    name = "anthropic"
    endpoint = "https://api.anthropic.com/v1/messages"
    api_version = "2023-06-01"

    def __init__(self, env: dict | None = None):
        self.env = os.environ if env is None else env
        self.model = self.env.get("CARDIO_LLM_MODEL") or None
        self.key_file = Path(self.env.get("CARDIO_LLM_API_KEY_FILE") or DEFAULT_KEY_FILE)

    def _key(self) -> str | None:
        try:
            key = self.key_file.read_text().strip()
        except OSError:
            return None
        return key or None

    def key_configured(self) -> bool:
        return self._key() is not None

    def blockers(self) -> list[str]:
        missing = []
        if not self.key_configured():
            missing.append(f"No API key: the key file {self.key_file} is missing or empty in the api container")
        if not self.model:
            missing.append("CARDIO_LLM_MODEL is not set")
        elif self.model not in ANTHROPIC_PRICES:
            missing.append(f"No verified price for model '{self.model}'; cost cannot be estimated")
        return missing

    def prices(self) -> dict | None:
        return ANTHROPIC_PRICES.get(self.model or "")

    def build_request(self, *, system: str, user_content: str, output_schema: dict, max_tokens: int,
                      effort: str) -> dict:
        return {
            "model": self.model, "max_tokens": max_tokens, "system": system,
            "messages": [{"role": "user", "content": user_content}],
            "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": output_schema}},
        }

    def send(self, request_body: dict, timeout_s: int) -> LiveResponse:
        key = self._key()
        if key is None:
            return LiveResponse("failed", None, 0.0, error="no_api_key")
        req = urllib.request.Request(self.endpoint, data=json.dumps(request_body).encode(), method="POST", headers={
            "x-api-key": key, "anthropic-version": self.api_version, "content-type": "application/json"})
        start = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as exc:  # report status and API error type only, never content
            err_type = None
            try:
                err_type = json.loads(exc.read()).get("error", {}).get("type")
            except Exception:
                pass
            return LiveResponse("failed", None, (time.perf_counter() - start) * 1000,
                                error=f"HTTP {exc.code}" + (f" {err_type}" if err_type else ""))
        except Exception as exc:
            return LiveResponse("failed", None, (time.perf_counter() - start) * 1000, error=type(exc).__name__)
        return LiveResponse("succeeded", body, (time.perf_counter() - start) * 1000)


FAKE_MARK = "[FAKE PROVIDER: no model was called]"


def _fake_output(body: dict) -> dict:
    """Schema-shaped canned output citing the first payload refs. For browser tests only."""
    payload = json.loads(body["messages"][0]["content"].split("\n", 1)[1])
    obs = [o["ref"] for o in payload.get("observations", [])][:1]
    st = lambda t: {"statement": f"{FAKE_MARK} {t}", "is_inference": True, "observation_refs": obs, "context_refs": [],
                    "evidence_refs": [], "prior_refs": []}
    required = body["output_config"]["format"]["schema"]["required"]
    if "answer" in required:
        return {"answer": f"{FAKE_MARK} Canned answer.", "established": [], "interpretations": [st("Canned interpretation.")],
                "unknown": [st("Canned unknown.")], "would_change_understanding": [st("Canned information need.")],
                "proposed_notes": [{"kind": "open_question", "text": f"{FAKE_MARK} Canned open question."}]}
    return {"summary": f"{FAKE_MARK} Canned investigation summary.", "conclusion_status": "insufficient_information",
            "learned": [], "interpretation_changes": [], "contradictory_or_limiting_evidence": [], "applicability": [],
            "unresolved": [st("Canned unresolved item.")], "distinguishing_information": [],
            "next_step": {"missing_history": [{"item": "Canned history item", "why": FAKE_MARK}],
                          "collectable_observations": [{"observation": "Canned observation", "why": FAKE_MARK}],
                          "clinical_review_questions": [{"question": "Canned clinical question", "why": FAKE_MARK}]},
            "protocol": {"stage": "observation_period", "title": f"{FAKE_MARK} Canned protocol", "question": "Canned",
                         "hypothesis": "Canned", "outcome": "Canned", "measurement_window": "Canned", "required_inputs": ["Canned"],
                         "comparison_baseline": "Canned", "analysis_approach": "Canned", "counts_against_hypothesis": "Canned",
                         "prediction": "Canned", "limitations": ["Canned"], "evidence_needed_before_intervention_prediction": ["Canned"]},
            "proposed_notes": []}


class FakeProvider:
    """Deterministic stand-in so the browser test can complete the research journey without a network call
    (CARDIO_RESEARCH_PROVIDER=fake, set only by scripts/e2e.sh). Every output is marked FAKE_MARK. D-058."""
    name = "fake"
    endpoint = "fake://no-network"

    def __init__(self, env: dict | None = None):
        self.model = "fake-model"

    def key_configured(self) -> bool:
        return True

    def blockers(self) -> list[str]:
        return []

    def prices(self) -> dict:
        return {"input": 0.0, "output": 0.0}

    build_request = AnthropicProvider.build_request

    def send(self, request_body: dict, timeout_s: int) -> LiveResponse:
        if "Research payload" not in request_body["messages"][0]["content"]:
            return LiveResponse("failed", None, 0.0, error="fake provider answers research-partner requests only")
        text = json.dumps(_fake_output(request_body))
        return LiveResponse("succeeded", {"id": "fake", "model": self.model, "stop_reason": "end_turn",
                                          "usage": {"input_tokens": 0, "output_tokens": 0},
                                          "content": [{"type": "text", "text": text}]}, 1.0)


def live_provider(env: dict | None = None) -> LiveProvider | None:
    env = os.environ if env is None else env
    name = env.get("CARDIO_RESEARCH_PROVIDER", "anthropic")
    if name == "fake":
        return FakeProvider(env)
    return AnthropicProvider(env) if name == "anthropic" else None
