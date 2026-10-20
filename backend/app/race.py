"""Benchmark runner: puzzles, trials and the agent loop.

For every puzzle, the four models race concurrently from the *same* scrambled state,
using the same engine, move set, recent-move policy, timeout and retry policy.
"""

from __future__ import annotations

import asyncio
import json
import random
import statistics
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from . import cube, solver
from . import ledger
from .adapters import BudgetStop, CachedError, Observation, TransportError, make_adapter
from .config import MODELS, MODELS_BY_KEY, OLLAMA_MODELS, PROVIDERS, RESULTS_DIR, SETTINGS, TEST_SETS

# Trial statuses
PENDING, RUNNING = "pending", "running"
SOLVED = "solved"
MOVE_LIMIT = "move_limit"          # reached MAX_MOVES without solving
OUT_OF_TIME = "out_of_time"        # exceeded TRIAL_TIME_LIMIT_S
TOO_MANY_INVALID = "invalid_limit"  # exceeded MAX_INVALID_OUTPUTS malformed responses
API_ERROR = "api_error"            # transport failed after all retries
BUDGET = "budget_exhausted"        # the API budget allowed no further request: not solved
CANCELLED = "cancelled"
FINISHED = {SOLVED, MOVE_LIMIT, OUT_OF_TIME, TOO_MANY_INVALID, API_ERROR, BUDGET, CANCELLED}


@dataclass
class MoveRecord:
    n: int
    move: str
    latency_ms: float
    confidence: float | None
    correct_stickers: int
    source: str = "live"            # live | cache | mock


@dataclass
class InvalidRecord:
    after_move: int
    raw: str
    error: str
    latency_ms: float


@dataclass
class Trial:
    model: str
    status: str = PENDING
    phase: str = ""                  # "thinking" / "deciding" while a call is in flight
    state: str = ""
    moves: list[MoveRecord] = field(default_factory=list)
    invalid: list[InvalidRecord] = field(default_factory=list)
    retries: int = 0
    call_latencies_ms: list[float] = field(default_factory=list)
    started_at: float | None = None
    ended_at: float | None = None
    total_time_s: float | None = None
    error: str | None = None
    rank: int | None = None
    final_distance: int | None = None     # exact distance to solved at the end (if <= 8)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    last_request: dict[str, Any] | None = None
    api_calls: int = 0                # actual HTTP requests sent (incl. retries / failures)
    cache_hits: int = 0
    live_latencies_ms: list[float] = field(default_factory=list)   # measured now, live
    cache_served_ms: list[float] = field(default_factory=list)     # time to serve cache hits

    @property
    def move_count(self) -> int:
        return len(self.moves)

    def elapsed(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.ended_at if self.ended_at is not None else time.time()
        return end - self.started_at

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["move_count"] = self.move_count
        d["elapsed_s"] = round(self.elapsed(), 3)
        d["avg_latency_ms"] = (
            round(statistics.fmean(self.call_latencies_ms), 1) if self.call_latencies_ms else None
        )
        d["correct_stickers"] = cube.correct_stickers(self.state) if self.state else None
        d["avg_live_latency_ms"] = (
            round(statistics.fmean(self.live_latencies_ms), 1) if self.live_latencies_ms else None
        )
        d["avg_cache_served_ms"] = (
            round(statistics.fmean(self.cache_served_ms), 3) if self.cache_served_ms else None
        )
        return d


@dataclass
class Puzzle:
    index: int
    test_set: str
    scramble: list[str]
    state: str
    optimal_moves: int | None
    optimal_solution: list[str] | None
    trials: dict[str, Trial] = field(default_factory=dict)
    status: str = PENDING

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "test_set": self.test_set,
            "scramble": self.scramble,
            "state": self.state,
            "optimal_moves": self.optimal_moves,
            "optimal_solution": self.optimal_solution,
            "status": self.status,
            "trials": {k: t.to_dict() for k, t in self.trials.items()},
        }


@dataclass
class Run:
    id: str
    test_set: str
    seed: int
    models: list[str]
    puzzles: list[Puzzle]
    mode: str
    created_at: float = field(default_factory=time.time)
    status: str = PENDING
    current: int = 0
    finished_at: float | None = None
    next_puzzle_at: float | None = None  # set during the pause between puzzles
    settings: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "test_set": self.test_set,
            "seed": self.seed,
            "models": self.models,
            "mode": self.mode,
            "status": self.status,
            "current": self.current,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "next_puzzle_at": self.next_puzzle_at,
            "settings": self.settings,
            "puzzles": [p.to_dict() for p in self.puzzles],
        }


def make_puzzles(test_set: str, count: int, seed: int) -> list[Puzzle]:
    spec = TEST_SETS[test_set]
    rng = random.Random(f"{test_set}:{seed}")
    puzzles = []
    for i in range(count):
        while True:
            scr = cube.random_scramble(rng.randint(spec["min"], spec["max"]), rng)
            st = cube.apply_moves(cube.SOLVED, scr)
            if cube.is_solved(st):
                continue
            # e.g. the live set: the state must be exactly N moves from solved (BFS-verified)
            if spec.get("exact_optimal") and solver.optimal_distance(st) != spec["exact_optimal"]:
                continue
            break
        sol = solver.optimal_solution(st)
        puzzles.append(Puzzle(i, test_set, scr, st, len(sol) if sol is not None else None,
                              list(sol) if sol is not None else None))
    return puzzles


def model_id_for(key: str, provider: str) -> str:
    return OLLAMA_MODELS[key] if provider == "ollama" else MODELS_BY_KEY[key].model_id


def create_run(test_set: str, count: int, seed: int | None = None,
               models: list[str] | None = None, provider: str = "mock") -> Run:
    if test_set not in TEST_SETS:
        raise ValueError(f"unknown test set {test_set!r}")
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}")
    if provider == "live" and SETTINGS.mock_mode:
        raise ValueError("No OpenRouter key configured: set OPENROUTER_API_KEY in .env.")
    models = [m for m in (models or [m.key for m in MODELS]) if m in MODELS_BY_KEY]
    if not models:
        raise ValueError("no valid models selected")
    seed = seed if seed is not None else random.randint(1, 10**6)
    solver.warm_up()
    puzzles = make_puzzles(test_set, count, seed)
    for p in puzzles:
        p.trials = {m: Trial(model=m, state=p.state) for m in models}
    return Run(
        id=time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4],
        test_set=test_set, seed=seed, models=models, puzzles=puzzles,
        mode=provider,
        settings={
            "provider": provider,
            "max_moves": SETTINGS.max_moves,
            "request_timeout_s": SETTINGS.request_timeout_s,
            "max_retries": SETTINGS.max_retries,
            "max_invalid_outputs": SETTINGS.max_invalid,
            "trial_time_limit_s": SETTINGS.trial_time_limit_s,
            "recent_moves_window": SETTINGS.recent_moves_window,
            "move_metric": "HTM (18 face moves)",
            "model_ids": {m: model_id_for(m, provider) for m in models},
            # A cache-only replay of an earlier live run (0 API calls): shown as such in the
            # UI and excluded from the statistics, which use the original run.
            "replay_from_cache": bool(provider == "live" and SETTINGS.cache_only),
            "budget_limits": ({"total": SETTINGS.max_total_api_calls, "claude": SETTINGS.max_claude_calls,
                               "per_decision_model": SETTINGS.max_decision_calls_per_model}
                              if provider == "live" else None),
        },
    )


async def run_trial(run: Run, puzzle: Puzzle, trial: Trial, cancel: asyncio.Event) -> None:
    spec = MODELS_BY_KEY[trial.model]
    adapter = make_adapter(spec, seed=run.seed * 1000 + puzzle.index, provider=run.mode)
    if hasattr(adapter, "warm"):
        await adapter.warm()  # local models: load weights before the clock starts
    trial.status = RUNNING
    trial.started_at = time.time()
    deadline = trial.started_at + SETTINGS.trial_time_limit_s
    history: list[str] = []
    try:
        while True:
            if cube.is_solved(trial.state):
                trial.status = SOLVED
                break
            if trial.move_count >= SETTINGS.max_moves:
                trial.status = MOVE_LIMIT
                break
            if len(trial.invalid) >= SETTINGS.max_invalid:
                trial.status = TOO_MANY_INVALID
                break
            if cancel.is_set():
                trial.status = CANCELLED
                break
            remaining = deadline - time.time()
            if remaining <= 0:
                trial.status = OUT_OF_TIME
                break
            obs = Observation(trial.state, history[-SETTINGS.recent_moves_window:],
                              trial.move_count, SETTINGS.max_moves)
            trial.phase = "thinking" if spec.category == "llm" else "deciding"
            call = asyncio.ensure_future(adapter.decide(obs))
            stop = asyncio.ensure_future(cancel.wait())
            try:
                done, _ = await asyncio.wait({call, stop}, timeout=remaining,
                                             return_when=asyncio.FIRST_COMPLETED)
            finally:
                stop.cancel()
            if call not in done:
                call.cancel()
                trial.status = CANCELLED if cancel.is_set() else OUT_OF_TIME
                break
            try:
                decision = call.result()
            except BudgetStop as exc:
                trial.retries += exc.retries
                trial.api_calls += exc.api_calls
                trial.status = BUDGET
                trial.error = f"API budget reached: {exc}"
                break
            except TransportError as exc:
                trial.retries += exc.retries
                trial.api_calls += exc.api_calls
                if isinstance(exc, CachedError):
                    trial.cache_hits += 1
                trial.status = API_ERROR
                trial.error = f"{exc} (after {exc.retries} retries)"
                break
            trial.retries += decision.retries
            trial.api_calls += decision.api_calls
            trial.call_latencies_ms.append(decision.latency_ms)
            if decision.source == "cache":
                trial.cache_hits += 1
                trial.cache_served_ms.append(round(decision.served_ms or 0.0, 3))
            elif decision.source == "live":
                trial.live_latencies_ms.append(round(decision.latency_ms, 1))
            trial.tokens_in += int(decision.usage.get("input_tokens") or 0)
            trial.tokens_out += int(decision.usage.get("output_tokens") or 0)
            trial.cost_usd += float(decision.usage.get("cost") or 0.0)
            trial.last_request = decision.request_preview
            if decision.move is None:
                trial.invalid.append(InvalidRecord(trial.move_count, decision.raw,
                                                   decision.error or "invalid", decision.latency_ms))
                continue
            trial.state = cube.apply_move(trial.state, decision.move)
            history.append(decision.move)
            trial.moves.append(MoveRecord(trial.move_count + 1, decision.move,
                                          round(decision.latency_ms, 1), decision.confidence,
                                          cube.correct_stickers(trial.state), decision.source))
    except Exception as exc:  # never let one model crash the race
        trial.status = API_ERROR
        trial.error = f"{type(exc).__name__}: {exc}"
    finally:
        trial.phase = ""
        trial.ended_at = time.time()
        trial.total_time_s = round(trial.ended_at - trial.started_at, 3)
        await adapter.aclose()
    trial.final_distance = await asyncio.to_thread(solver.optimal_distance, trial.state)


def rank_trials(puzzle: Puzzle) -> None:
    """Solved first (fewest moves, then fastest); unsolved by closeness, then time."""
    def key(t: Trial):
        if t.status == SOLVED:
            return (0, t.move_count, t.total_time_s or 0)
        return (1, -cube.correct_stickers(t.state), t.total_time_s or 0)

    for i, t in enumerate(sorted(puzzle.trials.values(), key=key), start=1):
        t.rank = i


class RunManager:
    def __init__(self) -> None:
        self.runs: dict[str, Run] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.cancels: dict[str, asyncio.Event] = {}

    def active(self) -> Run | None:
        return next((r for r in self.runs.values() if r.status in (PENDING, RUNNING)), None)

    def start(self, run: Run) -> None:
        # Mark it running before the task gets scheduled, so the first response the
        # client sees already says "running".
        run.status = RUNNING
        save_run(run)
        self.runs[run.id] = run
        self.cancels[run.id] = asyncio.Event()
        self.tasks[run.id] = asyncio.create_task(self._execute(run))

    def cancel(self, run_id: str) -> bool:
        ev = self.cancels.get(run_id)
        if ev is None:
            return False
        ev.set()
        return True

    async def _execute(self, run: Run) -> None:
        await execute_run(run, self.cancels[run.id], pause_s=SETTINGS.puzzle_pause_s)


async def execute_run(run: Run, cancel: asyncio.Event | None = None, on_update=None,
                      pause_s: float = 0.0) -> Run:
    """pause_s: seconds to hold each finished puzzle on screen before the next one
    starts (UI runs only; it is not part of any measured time)."""
    cancel = cancel or asyncio.Event()
    run.status = RUNNING
    save_run(run)  # persist immediately, so a crash mid-puzzle still leaves a record
    for p in run.puzzles:
        if cancel.is_set():
            p.status = CANCELLED
            for t in p.trials.values():
                t.status = CANCELLED
            continue
        if p.index > 0 and pause_s > 0:
            run.next_puzzle_at = time.time() + pause_s
            try:
                await asyncio.wait_for(cancel.wait(), timeout=pause_s)
            except asyncio.TimeoutError:
                pass
            run.next_puzzle_at = None
            if cancel.is_set():
                p.status = CANCELLED
                for t in p.trials.values():
                    t.status = CANCELLED
                continue
        run.current = p.index
        p.status = RUNNING
        save_run(run)
        if run.mode == "ollama":
            # One local GPU: run the models one after another so they don't slow each
            # other down (same puzzle, same rules; only the scheduling differs).
            for t in p.trials.values():
                await run_trial(run, p, t, cancel)
        else:
            await asyncio.gather(*(run_trial(run, p, t, cancel) for t in p.trials.values()))
        if cancel.is_set():
            # Stopped mid-puzzle: not a fair comparison, so it is not ranked or counted.
            p.status = CANCELLED
        else:
            rank_trials(p)
            p.status = "done"
        save_run(run)
        if on_update:
            on_update(run, p)
    run.status = CANCELLED if cancel.is_set() else "done"
    run.finished_at = time.time()
    save_run(run)
    return run


def save_run(run: Run) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / f"run-{run.id}.json").write_text(json.dumps(run.to_dict(), indent=1))


def load_saved_runs() -> list[dict[str, Any]]:
    out = []
    if RESULTS_DIR.exists():
        for f in sorted(RESULTS_DIR.glob("run-*.json")):
            try:
                out.append(json.loads(f.read_text()))
            except (OSError, json.JSONDecodeError):
                continue
    return out
