"""Runtime configuration, loaded from the project-root .env file (never sent to the browser)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class ModelSpec:
    key: str            # short stable key used in URLs / results
    name: str           # display name
    category: str       # "decision" | "llm"
    model_id: str       # OpenRouter model identifier
    interface: str      # "decisions" | "chat"
    color: str          # accent colour in the UI
    mock: dict = field(default_factory=dict)  # simulated behaviour in mock mode


@dataclass(frozen=True)
class Settings:
    api_key: str = os.getenv("OPENROUTER_API_KEY", "mock").strip()
    base_url: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai").rstrip("/")
    app_url: str = os.getenv("APP_URL", "http://localhost:8000")
    max_moves: int = _int("MAX_MOVES", 20)
    request_timeout_s: float = _float("REQUEST_TIMEOUT_S", 90.0)
    max_retries: int = _int("MAX_RETRIES", 1)
    max_invalid: int = _int("MAX_INVALID_OUTPUTS", 5)
    trial_time_limit_s: float = _float("TRIAL_TIME_LIMIT_S", 300.0)
    recent_moves_window: int = _int("RECENT_MOVES_WINDOW", 6)
    opus_reasoning_effort: str = os.getenv("OPUS_REASONING_EFFORT", "medium").strip()
    mock_latency_scale: float = _float("MOCK_LATENCY_SCALE", 1.0)
    puzzle_pause_s: float = _float("PUZZLE_PAUSE_S", 4.0)
    # --- API budget (OpenRouter only). Counted per actual HTTP attempt, persisted to disk,
    # never reset by a restart. Checked BEFORE every request.
    max_total_api_calls: int = _int("MAX_TOTAL_API_CALLS", 65)
    max_claude_calls: int = _int("MAX_CLAUDE_CALLS", 5)
    max_decision_calls_per_model: int = _int("MAX_DECISION_CALLS_PER_MODEL", 20)
    key_hard_limit: int = _int("KEY_HARD_LIMIT", 100)  # informational: the key dies at this
    budget_file: str = os.getenv("BUDGET_FILE", "")
    cache_file: str = os.getenv("CACHE_FILE", "")
    api_log_file: str = os.getenv("API_LOG_FILE", "")
    # Replay cached responses at their originally measured live latency (for re-recording).
    cache_replay_realtime: bool = os.getenv("CACHE_REPLAY_REALTIME", "0").strip() in ("1", "true", "yes")
    # Never send a request: anything not in the cache fails instead (safe replays).
    cache_only: bool = os.getenv("CACHE_ONLY", "0").strip() in ("1", "true", "yes")
    # --- Ollama (local open models, free, no budget)
    ollama_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    student_name: str = os.getenv("STUDENT_NAME", "Your Name")
    student_roll: str = os.getenv("STUDENT_ROLL", "Roll No. 00-0000")

    @property
    def mock_mode(self) -> bool:
        """True when no real OpenRouter key is configured."""
        return self.api_key == "" or self.api_key.lower() == "mock"


SETTINGS = Settings()

# Test sets from section 6 of the assignment.
TEST_SETS = {
    "warmup": {"label": "Warm-up", "min": 3, "max": 4, "default_puzzles": 3},
    "primary": {"label": "Primary benchmark", "min": 4, "max": 5, "default_puzzles": 5},
    "extension": {"label": "Extension", "min": 15, "max": 20, "default_puzzles": 3},
    # The live OpenRouter experiment: exactly 3 moves from solved (verified by BFS).
    "live3": {"label": "Live (3 from solved)", "min": 3, "max": 3,
              "default_puzzles": 1, "exact_optimal": 3},
}

# Providers. "live" = OpenRouter (real, budgeted), "ollama" = local open models (free),
# "mock" = offline simulation.
PROVIDERS = {
    "mock": "Mock (simulated)",
    "ollama": "Ollama (local)",
    "live": "OpenRouter (live)",
}

# Mock profiles: p_opt = probability the simulated model picks a move that starts a
# shortest solution; latency in seconds (mean, jitter); invalid = malformed-output rate.
MODELS: list[ModelSpec] = [
    ModelSpec(
        "jev", "Jev 1.13", "decision", os.getenv("MODEL_JEV", "typesafe/jev-1.13"),
        "decisions", "#3987e5",
        {"p_opt": 0.55, "latency": (0.32, 0.10), "invalid": 0.0},
    ),
    ModelSpec(
        "luna", "GPT-6 Luna Decisions", "decision",
        os.getenv("MODEL_LUNA", "openai/gpt-6-luna-decisions"),
        "decisions", "#d95926",
        {"p_opt": 0.5, "latency": (0.45, 0.15), "invalid": 0.0},
    ),
    ModelSpec(
        "clef", "Cloudflare Clef", "decision", os.getenv("MODEL_CLEF", "cloudflare/clef"),
        "decisions", "#199e70",
        {"p_opt": 0.4, "latency": (0.22, 0.06), "invalid": 0.0},
    ),
    ModelSpec(
        "opus", "Claude Opus 5.5", "llm", os.getenv("MODEL_OPUS", "anthropic/claude-opus-5.5"),
        "chat", "#c98500",
        {"p_opt": 0.9, "latency": (5.5, 1.8), "invalid": 0.02},
    ),
]
MODELS_BY_KEY = {m.key: m for m in MODELS}

# Local stand-ins for each slot when running on Ollama: small fast models in the three
# System-1 slots, larger open "frontier-style" models in the LLM slot.
OLLAMA_MODELS = {
    "jev": os.getenv("OLLAMA_MODEL_JEV", "gemma3:1b"),
    "luna": os.getenv("OLLAMA_MODEL_LUNA", "llama3.2:1b"),
    "clef": os.getenv("OLLAMA_MODEL_CLEF", "qwen2.5:1.5b"),
    "opus": os.getenv("OLLAMA_MODEL_OPUS", "qwen3:4b"),
}

RESULTS_DIR = Path(os.getenv("RESULTS_DIR") or ROOT / "results")
# Budget counters, response cache and the request log live outside results/ run files so
# deleting runs never resets them.
STATE_DIR = Path(os.getenv("STATE_DIR") or ROOT / "state")
FRONTEND_DIR = ROOT / "frontend"
