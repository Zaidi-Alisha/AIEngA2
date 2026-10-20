"""Model adapters. Every adapter implements the same game-action contract:

    observation (cube state + recent moves)  ->  Decision(move | invalid, latency, ...)

* DecisionsAdapter - OpenRouter Decisions API (POST /api/alpha/decisions), one typed
  "choice" question whose criteria are the 18 legal moves.
* ChatAdapter      - OpenRouter chat completions (POST /api/v1/chat/completions) with a
  JSON-schema constrained {"move": "<one of 18>"} response.
* OllamaAdapter    - local open models through Ollama /api/chat (same chat contract).
* MockAdapter      - offline simulation. It builds the exact same request payload as the
  real adapter, then simulates latency and a policy.

Every real request goes through _HttpAdapter._request: persistent cache first, then the
persistent API budget (OpenRouter only), then HTTP, with every attempt logged.

Both real interfaces get the same state object, the same instructions, the same option
definitions and the same recent-move window; only the transport differs.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from . import cube, ledger, solver
from .config import OLLAMA_MODELS, SETTINGS, ModelSpec

INSTRUCTIONS = (
    "You are solving a 3x3 Rubik's Cube. Choose the single next move most likely to "
    "progress toward the solved cube (every face a single colour) in as few total moves "
    "as possible. The state uses the 54-character facelet string in URFDLB face order, "
    "9 stickers per face, read row by row; each letter names the face whose centre has "
    "that colour. 'faces' shows the same data as three rows per face. Moves use standard "
    "notation in the half-turn metric (X = clockwise 90 degrees looking at face X, "
    "X' = counterclockwise, X2 = 180 degrees). Avoid undoing your recent moves."
)

QUESTION_KEY = "next_move"


@dataclass
class Observation:
    state: str
    recent_moves: list[str]
    moves_made: int
    max_moves: int

    def to_state(self) -> dict[str, Any]:
        """The shared state object sent to every model."""
        return {
            "cube_facelets": self.state,
            "facelet_order": "U1-U9 R1-R9 F1-F9 D1-D9 L1-L9 B1-B9",
            "faces": cube.describe_state(self.state),
            "solved_state": cube.SOLVED,
            "recent_moves": self.recent_moves,
            "moves_made": self.moves_made,
            "moves_remaining": self.max_moves - self.moves_made,
        }


@dataclass
class Decision:
    move: str | None                 # validated move, or None when the output was invalid
    raw: str                         # raw model output (for the log)
    latency_ms: float                # wall time of the successful call (incl. retries)
    error: str | None = None         # malformed output / transport error description
    retries: int = 0
    confidence: float | None = None
    probabilities: dict[str, float] | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    request_preview: dict[str, Any] | None = None
    source: str = "live"             # "live" | "cache" | "mock"
    api_calls: int = 0               # actual HTTP attempts for this decision (incl. retries)
    served_ms: float | None = None   # wall time to serve from cache (cache hits only)


class TransportError(Exception):
    def __init__(self, msg: str, retries: int = 0, api_calls: int = 0):
        super().__init__(msg)
        self.retries = retries
        self.api_calls = api_calls  # actual HTTP attempts made before giving up


class BudgetStop(TransportError):
    """The API budget forbids another request: the trial ends as not solved."""


class CachedError(TransportError):
    """A request that failed live (after its retries), replayed from the cache."""


def decisions_payload(spec: ModelSpec, obs: Observation) -> dict[str, Any]:
    return {
        "model": spec.model_id,
        "state": obs.to_state(),
        "questions": {
            QUESTION_KEY: {
                "type": "choice",
                "instructions": INSTRUCTIONS,
                "criteria": cube.move_criteria(),
            }
        },
    }


def chat_payload(spec: ModelSpec, obs: Observation) -> dict[str, Any]:
    criteria = cube.move_criteria()
    user = {
        "state": obs.to_state(),
        "question": {
            QUESTION_KEY: {"type": "choice", "instructions": INSTRUCTIONS, "criteria": criteria}
        },
        "response_format": 'Reply with JSON only: {"move": "<one option key>"}',
    }
    payload: dict[str, Any] = {
        "model": spec.model_id,
        "messages": [
            {
                "role": "system",
                "content": "You are a Rubik's Cube solving agent. You must answer with exactly "
                "one legal move as a JSON object and nothing else.",
            },
            {"role": "user", "content": json.dumps(user)},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "cube_move",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {"move": {"type": "string", "enum": list(criteria)}},
                    "required": ["move"],
                    "additionalProperties": False,
                },
            },
        },
        "provider": {"require_parameters": True},
        "usage": {"include": True},  # ask OpenRouter to report the actual cost
        "max_tokens": 16000,
    }
    if SETTINGS.opus_reasoning_effort:
        payload["reasoning"] = {"effort": SETTINGS.opus_reasoning_effort}
    return payload


def parse_decisions_response(body: dict[str, Any]) -> tuple[str | None, str | None, float | None, dict | None]:
    """-> (move, error, confidence, probabilities). Never coerces an invalid answer."""
    answer = (body.get("answers") or {}).get(QUESTION_KEY)
    if not isinstance(answer, dict):
        return None, "response has no answers.next_move", None, None
    choice = answer.get("choice")
    conf = answer.get("confidence")
    probs = answer.get("probabilities")
    conf = float(conf) if isinstance(conf, (int, float)) else None
    probs = probs if isinstance(probs, dict) else None
    if not isinstance(choice, str) or not cube.is_valid_move(choice):
        return None, f"invalid choice {choice!r}", conf, probs
    return choice, None, conf, probs


def parse_chat_content(content: str | None) -> tuple[str | None, str | None]:
    """Strict: the content must be a JSON object with one valid 'move'."""
    if not content or not content.strip():
        return None, "empty response"
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None, "response is not valid JSON"
    if not isinstance(data, dict) or "move" not in data:
        return None, "JSON has no 'move' field"
    move = data["move"]
    if not isinstance(move, str) or not cube.is_valid_move(move):
        return None, f"illegal move {move!r}"
    return move, None


def normalize_usage(u: dict[str, Any] | None) -> dict[str, Any]:
    """OpenRouter decisions / chat and Ollama report usage differently; unify it."""
    u = u or {}
    return {
        "input_tokens": int(u.get("input_tokens") or u.get("prompt_tokens") or u.get("prompt_eval_count") or 0),
        "output_tokens": int(u.get("output_tokens") or u.get("completion_tokens") or u.get("eval_count") or 0),
        "cost": float(u.get("cost") or 0.0),
    }


class BaseAdapter:
    def __init__(self, spec: ModelSpec):
        self.spec = spec

    async def decide(self, obs: Observation) -> Decision:  # pragma: no cover - interface
        raise NotImplementedError

    async def aclose(self) -> None:
        pass


class _HttpAdapter(BaseAdapter):
    """Shared request path for every real model call:

        cache lookup -> (miss) budget reserve -> HTTP -> log -> cache store

    The budget is reserved BEFORE each attempt (retries included), and the trial loop is
    bounded by moves, invalid outputs, time and budget, so no request loop is unbounded.
    """

    path = ""
    provider = "live"

    def __init__(self, spec: ModelSpec, model_id: str | None = None):
        super().__init__(spec)
        self.model_id = model_id or spec.model_id
        self.seen: dict[str, int] = {}  # payload hash -> times asked in this trial
        self.client = self._client()

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=SETTINGS.base_url,
            timeout=httpx.Timeout(SETTINGS.request_timeout_s, connect=15.0),
            headers={
                "Authorization": f"Bearer {SETTINGS.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": SETTINGS.app_url,
                "X-Title": "Rubik's Cube Race",
            },
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    async def _request(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        # The n-th identical request in a trial gets its own cache slot: re-asking after an
        # invalid answer is a fresh call live, and a replay reproduces the same sequence.
        base = ledger.cache_key(self.provider, self.path, payload)
        n = self.seen.get(base, 0)
        self.seen[base] = n + 1
        key = f"{base}:{n}"
        t0 = time.perf_counter()
        hit = ledger.cache_get(key)
        if hit is not None:
            served = (time.perf_counter() - t0) * 1000
            if SETTINGS.cache_replay_realtime:
                await asyncio.sleep(hit["live_latency_ms"] / 1000)
            if "error" in hit:  # the live request failed: replay the failure, send nothing
                ledger.log({"event": "cache_hit_error", "provider": self.provider, "model": self.model_id,
                            "endpoint": self.path, "key": key[:16], "error": hit["error"][:200]})
                raise CachedError(hit["error"], 0, 0)
            ledger.log({"event": "cache_hit", "provider": self.provider, "model": self.model_id,
                        "endpoint": self.path, "key": key[:16], "served_ms": round(served, 2),
                        "original_live_latency_ms": hit["live_latency_ms"]})
            return hit["body"], {"source": "cache", "api_calls": 0, "retries": 0,
                                 "latency_ms": hit["live_latency_ms"], "served_ms": served}

        if SETTINGS.cache_only:
            ledger.log({"event": "cache_only_miss", "provider": self.provider, "model": self.model_id})
            raise BudgetStop("cache-only replay: this request was never made live", 0, 0)
        retries = attempts = 0
        t_start = time.perf_counter()
        while True:
            counters: dict[str, int] = {}
            if self.provider == "live":
                try:
                    counters = ledger.reserve(self.model_id, self.spec.category)
                except ledger.BudgetExceeded as exc:
                    ledger.log({"event": "budget_block", "model": self.model_id, "reason": str(exc)})
                    raise BudgetStop(str(exc), retries, attempts) from exc
            attempts += 1
            t_att = time.perf_counter()
            try:
                resp = await self.client.post(self.path, json=payload)
                status = resp.status_code
                if status == 429 or status >= 500:
                    raise TransportError(f"HTTP {status}: {resp.text[:300]}")
                if status >= 400:
                    raise TransportError(f"HTTP {status}: {resp.text[:500]}")
                body = resp.json()
                if isinstance(body, dict) and body.get("error"):
                    raise TransportError(f"API error: {json.dumps(body['error'])[:500]}")
            except (httpx.TimeoutException, httpx.TransportError, TransportError, ValueError) as exc:
                msg = str(exc) or type(exc).__name__
                ledger.log({"event": "request_failed", "provider": self.provider, "model": self.model_id,
                            "endpoint": self.path, "attempt": attempts, "error": msg[:300],
                            "latency_ms": round((time.perf_counter() - t_att) * 1000, 1), "budget": counters})
                retryable = not (msg.startswith("HTTP 4") and not msg.startswith("HTTP 429"))
                if retries >= SETTINGS.max_retries or not retryable:
                    # Cache the final failure too, so a replay reproduces it without a call.
                    ledger.cache_put(key, {"error": msg, "retries": retries, "api_calls": attempts,
                                           "live_latency_ms": round((time.perf_counter() - t_start) * 1000, 1),
                                           "model": self.model_id, "provider": self.provider,
                                           "endpoint": self.path, "created": time.time()})
                    raise TransportError(msg, retries, attempts) from exc
                retries += 1
                await asyncio.sleep(1.5 * retries)
                continue
            ms = (time.perf_counter() - t_start) * 1000
            usage = normalize_usage(body if self.provider == "ollama" else body.get("usage"))
            if self.provider == "live":
                ledger.add_cost(usage["cost"])
            ledger.log({"event": "request_ok", "provider": self.provider, "model": self.model_id,
                        "endpoint": self.path, "attempt": attempts, "latency_ms": round(ms, 1),
                        "usage": usage, "budget": counters})
            ledger.cache_put(key, {"body": body, "live_latency_ms": round(ms, 1), "model": self.model_id,
                                   "provider": self.provider, "endpoint": self.path, "created": time.time()})
            return body, {"source": "live", "api_calls": attempts, "retries": retries,
                          "latency_ms": ms, "served_ms": None, "usage": usage}


def _finish(d: Decision, info: dict[str, Any]) -> Decision:
    d.source = info["source"]
    d.api_calls = info["api_calls"]
    d.served_ms = info["served_ms"]
    d.usage = info.get("usage") or {"input_tokens": 0, "output_tokens": 0, "cost": 0.0}  # cache: nothing spent now
    return d


class DecisionsAdapter(_HttpAdapter):
    path = "/api/alpha/decisions"

    async def decide(self, obs: Observation) -> Decision:
        payload = decisions_payload(self.spec, obs)
        body, info = await self._request(payload)
        move, err, conf, probs = parse_decisions_response(body)
        raw = json.dumps(body.get("answers", body))[:600]
        return _finish(Decision(move, raw, info["latency_ms"], err, info["retries"], conf, probs), info)


class ChatAdapter(_HttpAdapter):
    path = "/api/v1/chat/completions"

    async def decide(self, obs: Observation) -> Decision:
        payload = chat_payload(self.spec, obs)
        body, info = await self._request(payload)
        try:
            content = body["choices"][0]["message"].get("content")
        except (KeyError, IndexError, TypeError):
            content = None
        move, err = parse_chat_content(content)
        return _finish(Decision(move, (content or "")[:600], info["latency_ms"], err, info["retries"]), info)


class OllamaAdapter(_HttpAdapter):
    """Local open model through Ollama's /api/chat, with the same messages and the same
    JSON-schema move contract as the chat adapter. Ollama has no Decisions API, so every
    slot uses chat. Free, so there is no budget, but it is still cached and logged."""

    path = "/api/chat"
    provider = "ollama"

    async def warm(self) -> None:
        """Load the model into memory before the trial clock starts (cold start is not
        model latency). An empty generate request only loads the model."""
        try:
            await self.client.post("/api/generate", json={"model": self.model_id, "keep_alive": "15m"})
        except httpx.HTTPError:
            pass

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=SETTINGS.ollama_url,
                                 timeout=httpx.Timeout(SETTINGS.request_timeout_s, connect=10.0))

    async def decide(self, obs: Observation) -> Decision:
        chat = chat_payload(self.spec, obs)
        payload = {
            "model": self.model_id,
            "messages": chat["messages"],
            "format": chat["response_format"]["json_schema"]["schema"],
            "stream": False,
            # Mirror the live setup: the frontier slot may reason (Claude runs with
            # reasoning.effort), System-1 slots answer directly. Default sampling
            # temperature, as on OpenRouter (temperature 0 made small models repeat
            # one move forever: see results/archive/).
            "think": self.spec.category == "llm",
        }
        body, info = await self._request(payload)
        content = (body.get("message") or {}).get("content")
        move, err = parse_chat_content(content)
        return _finish(Decision(move, (content or "")[:600], info["latency_ms"], err, info["retries"]), info)


class MockAdapter(BaseAdapter):
    """Offline stand-in. It never touches the network but follows the same contract,
    including occasional malformed outputs that the engine must reject and count."""

    def __init__(self, spec: ModelSpec, seed: int):
        super().__init__(spec)
        self.rng = random.Random(f"{spec.key}:{seed}")
        self.profile = spec.mock

    def _greedy(self, obs: Observation) -> str:
        # One-step lookahead on matching stickers, avoiding an immediate undo.
        last = obs.recent_moves[-1] if obs.recent_moves else None
        scored = []
        for m in cube.MOVES:
            if last and m[0] == last[0]:
                continue
            scored.append((cube.correct_stickers(cube.apply_move(obs.state, m)), self.rng.random(), m))
        scored.sort(reverse=True)
        return scored[0][2]

    def _policy(self, obs: Observation) -> tuple[str, float, dict[str, float]]:
        best = solver.best_next_moves(obs.state, limit=7)  # cheap lookahead
        if best and self.rng.random() < self.profile["p_opt"]:
            move = self.rng.choice(best)
        elif self.rng.random() < 0.5:
            move = self._greedy(obs)
        else:
            move = self.rng.choice(cube.MOVES)
        # Plausible probability distribution, peaked on the chosen move.
        weights = {m: self.rng.random() * 0.2 for m in cube.MOVES}
        weights[move] += 1.0 + self.rng.random() * 2.0
        total = sum(weights.values())
        probs = {m: round(w / total, 4) for m, w in weights.items()}
        return move, probs[move], probs

    async def decide(self, obs: Observation) -> Decision:
        if self.spec.interface == "decisions":
            payload = decisions_payload(self.spec, obs)
        else:
            payload = chat_payload(self.spec, obs)
        mean, jitter = self.profile["latency"]
        delay = max(0.03, self.rng.gauss(mean, jitter)) * SETTINGS.mock_latency_scale
        t0 = time.perf_counter()
        await asyncio.sleep(delay)
        ms = (time.perf_counter() - t0) * 1000
        # Solver work is simulation overhead, so it runs off the event loop and is not timed.
        move, conf, probs = await asyncio.to_thread(self._policy, obs)
        preview = {"endpoint": DecisionsAdapter.path if self.spec.interface == "decisions"
                   else ChatAdapter.path, "model": payload["model"]}
        if self.rng.random() < self.profile.get("invalid", 0.0):
            content = '{"move": "R3"}' if self.rng.random() < 0.5 else "I think R' is best."
            m, err = parse_chat_content(content)
            return Decision(m, content, ms, err, request_preview=preview, source="mock")
        if self.spec.interface == "decisions":
            body = {"answers": {QUESTION_KEY: {"type": "choice", "choice": move,
                                               "confidence": round(conf, 3),
                                               "probabilities": probs}}}
            m, err, c, p = parse_decisions_response(body)
            raw = json.dumps({"choice": move, "confidence": round(conf, 3)})
            return Decision(m, raw, ms, err, 0, c, p, request_preview=preview, source="mock")
        content = json.dumps({"move": move})
        m, err = parse_chat_content(content)
        return Decision(m, content, ms, err, request_preview=preview, source="mock")


def make_adapter(spec: ModelSpec, seed: int, provider: str = "mock") -> BaseAdapter:
    if provider == "mock":
        return MockAdapter(spec, seed)
    if provider == "ollama":
        return OllamaAdapter(spec, OLLAMA_MODELS[spec.key])
    if provider == "live":
        if SETTINGS.mock_mode:
            raise ValueError("No OpenRouter key configured (OPENROUTER_API_KEY=mock).")
        return DecisionsAdapter(spec) if spec.interface == "decisions" else ChatAdapter(spec)
    raise ValueError(f"unknown provider {provider!r}")
