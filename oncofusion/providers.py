"""Explicit mock and OpenAI-compatible backends; no silent backend fallback."""
from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlsplit

import httpx
from .evidence import polarity, quote_document, tokens
from .schemas import AnalysisOutput, DecisionOutput, Document, Finding, EvidenceSection, ResearchIntegration


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, reply: ModelReply | None = None):
        super().__init__(message)
        # An unusable answer can still have billable, reported token usage.
        self.reply = reply


@dataclass
class ModelReply:
    content: str
    input_tokens: int
    output_tokens: int
    attempts: int = 1
    estimated: bool = False


class Provider(Protocol):
    name: str
    model: str
    simulated: bool
    input_price: float | None
    output_price: float | None

    def complete(self, system: str, payload: dict, max_tokens: int,
                 temperature: float, seed: int) -> ModelReply: ...


@dataclass
class MockProvider:
    """Deterministic lexical plumbing simulator. It is not a biomedical model."""
    name: str = "mock"
    model: str = "lexical-simulator-v1"
    simulated: bool = True
    input_price: float = 0.0
    output_price: float = 0.0

    def complete(self, system: str, payload: dict, max_tokens: int,
                 temperature: float, seed: int) -> ModelReply:
        docs = [Document.model_validate(d) for d in payload["sources"]]
        signals = payload["signals"]
        findings = []
        claim_direction = polarity(payload["question"])
        query_terms = set(tokens(payload["question"]))
        for doc in docs:
            matches = signals.get("matches", {}).get(doc.id, {})
            if "mismatch" in matches.values():
                continue
            overlap = len(query_terms.intersection(tokens(doc.text)))
            direction = signals.get("directions", {}).get(doc.id, "unknown")
            relation = "NEI"
            if overlap >= 2 and (payload["task"] != "verification" or doc.kind == "literature"):
                relation = "SUPPORTS"
                if claim_direction != "unknown" and direction != "unknown" and claim_direction != direction:
                    relation = "REFUTES"
            if payload["task"] == "verification" and relation not in payload.get("verification_labels", ("SUPPORTS", "REFUTES", "NEI")):
                # The lexical simulator cannot infer a supported revision from a contradiction.
                relation = "NEI"
            findings.append(Finding(statement=doc.text[:300], relation=relation,
                                    citations=[quote_document(doc)]))
        if payload["role"] == "decision":
            counts = {label: sum(f.relation == label for f in findings) for label in ("SUPPORTS", "REFUTES")}
            unresolved = []
            if payload["task"] == "verification":
                answer = "NEI" if counts["SUPPORTS"] == counts["REFUTES"] else max(counts, key=counts.get)
                if counts["SUPPORTS"] and counts["REFUTES"]:
                    unresolved.append("Conflicting lexical evidence requires semantic review.")
            elif payload["task"] == "mcq":
                source_text = " ".join(d.text for d in docs)
                # When available, the latest structured event is the simulator's temporal focus.
                timeline = signals.get("timeline", [])
                if timeline:
                    source_text = timeline[-1]["text"]
                source_terms = set(tokens(source_text))
                scores = {k: len(source_terms.intersection(tokens(v))) for k, v in payload["options"].items()}
                answer = max(sorted(scores), key=scores.get)
            else:
                answer = "Synthetic evidence summary: " + (findings[0].statement if findings else "insufficient source material")
            out = DecisionOutput(answer=answer, explanation="SIMULATED lexical output for software testing only.",
                                 citations=[f.citations[0] for f in findings[:30]], unresolved=unresolved,
                                 confidence=None)
        else:
            relevant = findings[:20]
            if not docs and payload["role"] == "verifier" and payload["board"]:
                board = payload["board"]
                if isinstance(board, str):
                    board = [json.loads(line) for line in board.splitlines() if line]
                findings = [Finding.model_validate(f) for f in board]
            if payload["role"] == "verifier":
                relevant = [f for f in findings if f.relation != "NEI"][:20]
            unresolved = [] if relevant else ["No matching evidence in the provided source view."]
            out = AnalysisOutput(findings=relevant, unresolved=unresolved,
                                 requery=payload["question"] if unresolved and payload["role"] == "verifier" else "")
        if payload["role"] == "decision" and payload["task"] == "synthesis" and "task_scope" in payload:
            # The simulator demonstrates the schema, never a mechanistic efficacy chain.
            out.integration = ResearchIntegration(**{
                name: EvidenceSection(status="insufficient_evidence",
                                      statement="SIMULATED: this evidence link requires real-model and source review.")
                for name in ResearchIntegration.model_fields})
        content = out.model_dump_json()
        while len(content) // 4 > max_tokens:
            if isinstance(out, AnalysisOutput) and out.findings:
                out.findings.pop()
            elif isinstance(out, DecisionOutput) and out.citations:
                out.citations.pop()
            else:
                raise ProviderError("simulated output exceeds configured output-token limit")
            content = out.model_dump_json()
        return ModelReply(content, max(1, len(json.dumps(payload, ensure_ascii=False)) // 4),
                          max(1, len(content) // 4), estimated=True)


@dataclass
class OpenAICompatibleProvider:
    base_url: str
    model: str
    api_key: str = field(repr=False)
    timeout: float = 60.0
    retries: int = 2
    json_mode: bool = True
    token_parameter: str = "max_tokens"
    send_temperature: bool = True
    send_seed: bool = True
    input_price: float | None = None
    output_price: float | None = None
    transport: httpx.BaseTransport | None = field(default=None, repr=False)
    name: str = field(default="openai_compatible", init=False)
    simulated: bool = field(default=False, init=False)

    def __post_init__(self):
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.query or parsed.fragment or parsed.username:
            raise ValueError("base URL must be a plain HTTP(S) API root")
        if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("remote providers require HTTPS")
        if not self.api_key or not self.model:
            raise ValueError("real provider requires a model and API key")
        if self.token_parameter not in ("max_tokens", "max_completion_tokens"):
            raise ValueError("unsupported token parameter")
        if not 0 <= self.retries <= 5 or (not math.isfinite(self.timeout) or self.timeout <= 0):
            raise ValueError("invalid timeout or retry limit")
        if any(p is not None and (not math.isfinite(p) or p < 0) for p in (self.input_price, self.output_price)):
            raise ValueError("prices must be nonnegative")

    def complete(self, system: str, payload: dict, max_tokens: int,
                 temperature: float, seed: int) -> ModelReply:
        body = {"model": self.model, "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            self.token_parameter: max_tokens}
        if self.send_temperature:
            body["temperature"] = temperature
        if self.send_seed:
            body["seed"] = seed
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": "Bearer " + self.api_key}
        with httpx.Client(timeout=self.timeout, transport=self.transport, follow_redirects=False) as client:
            for attempt in range(self.retries + 1):
                try:
                    response = client.post(self.base_url.rstrip("/") + "/chat/completions", json=body, headers=headers)
                except httpx.RequestError as exc:
                    if attempt == self.retries:
                        raise ProviderError("model transport failed; upstream usage may be unknown") from exc
                    time.sleep(min(.25 * 2**attempt, 2))
                    continue
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < self.retries:
                        time.sleep(min(.25 * 2**attempt, 2))
                        continue
                if response.status_code != 200:
                    # Do not leak response bodies, URLs, prompts, or credentials into API errors.
                    raise ProviderError(f"model endpoint returned HTTP {response.status_code}")
                partial = None
                try:
                    data = response.json()
                    usage = data.get("usage")
                    if usage is not None:
                        incoming, outgoing = usage["prompt_tokens"], usage["completion_tokens"]
                        if type(incoming) is not int or type(outgoing) is not int or min(incoming, outgoing) < 0:
                            raise ValueError("invalid token usage")
                        partial = ModelReply("", incoming, outgoing, attempt + 1, False)
                    choice = data["choices"][0]
                    if choice.get("finish_reason") == "length":
                        raise ProviderError("model output was truncated; raise max_output_tokens", reply=partial)
                    content = choice["message"]["content"]
                    if not isinstance(content, str) or not content.strip():
                        raise ValueError("empty content")
                    if partial is not None:
                        partial.content = content
                        return partial
                    return ModelReply(content, len(json.dumps(body, ensure_ascii=False)) // 4,
                                      len(content) // 4, attempt + 1, True)
                except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
                    raise ProviderError("invalid model response envelope", reply=partial) from exc
        raise AssertionError("retry loop must return or raise")


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name, str(default)).lower()
    if value not in ("true", "false"):
        raise ValueError(name + " must be true or false")
    return value == "true"


def provider_identity(provider: Provider) -> dict:
    """Include inference-affecting settings in cache identities; credentials stay private."""
    identity = {"provider": provider.name, "model": provider.model, "simulated": provider.simulated}
    if isinstance(provider, OpenAICompatibleProvider):
        identity.update({key: getattr(provider, key) for key in
                         ("base_url", "timeout", "retries", "json_mode", "token_parameter", "send_temperature", "send_seed", "input_price", "output_price")})
    return identity


def provider_from_env() -> Provider:
    backend = os.getenv("ONCOFUSION_PROVIDER", "mock")
    if backend == "mock":
        return MockProvider()
    if backend != "openai_compatible":
        raise ValueError("unknown ONCOFUSION_PROVIDER")
    missing = [key for key in ("ONCOFUSION_BASE_URL", "ONCOFUSION_MODEL", "ONCOFUSION_API_KEY") if not os.getenv(key)]
    if missing:
        raise ValueError("missing real-provider environment variables: " + ", ".join(missing))
    prices = [float(os.environ[k]) if k in os.environ else None for k in ("ONCOFUSION_INPUT_PRICE", "ONCOFUSION_OUTPUT_PRICE")]
    return OpenAICompatibleProvider(os.environ["ONCOFUSION_BASE_URL"], os.environ["ONCOFUSION_MODEL"],
                                    os.environ["ONCOFUSION_API_KEY"],
                                    timeout=float(os.getenv("ONCOFUSION_TIMEOUT", "60")),
                                    retries=int(os.getenv("ONCOFUSION_RETRIES", "2")),
                                    json_mode=env_bool("ONCOFUSION_JSON_MODE", True),
                                    send_temperature=env_bool("ONCOFUSION_SEND_TEMPERATURE", True),
                                    send_seed=env_bool("ONCOFUSION_SEND_SEED", True),
                                    token_parameter=os.getenv("ONCOFUSION_TOKEN_PARAMETER", "max_tokens"),
                                    input_price=prices[0], output_price=prices[1])
