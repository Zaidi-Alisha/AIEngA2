"""Persistent API budget, response cache and request log.

Rules (from the assignment's budget instructions):
  * Every *actual* HTTP attempt to OpenRouter counts, including failures and retries.
  * The counter is checked and incremented BEFORE the request is sent, and saved to disk
    immediately, so a crash can never "forget" a request.
  * Limits: Claude <= MAX_CLAUDE_CALLS, each decision model <= MAX_DECISION_CALLS_PER_MODEL,
    everything <= MAX_TOTAL_API_CALLS. Counters are never reset by a restart.
  * The cache is checked before every request; a hit costs no budget. Cache hits and live
    calls are logged and timed separately.

Files (in STATE_DIR, default ./state):
  api_budget.json   counters per provider/model
  api_cache.json    request-hash -> response body + originally measured live latency
  api_log.jsonl     one line per request attempt or cache hit
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from .config import SETTINGS, STATE_DIR

_lock = threading.RLock()


def _path(setting: str, default_name: str) -> Path:
    return Path(setting) if setting else STATE_DIR / default_name


def budget_path() -> Path:
    return _path(SETTINGS.budget_file, "api_budget.json")


def cache_path() -> Path:
    return _path(SETTINGS.cache_file, "api_cache.json")


def log_path() -> Path:
    return _path(SETTINGS.api_log_file, "api_log.jsonl")


def _read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(p: Path, data) -> None:
    """Atomic write: never leaves a half-written counter or cache file."""
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, p)


# ------------------------------------------------------------------------ budget
class BudgetExceeded(Exception):
    """Raised instead of sending a request that would break a limit."""


def limit_for(category: str) -> int:
    return SETTINGS.max_claude_calls if category == "llm" else SETTINGS.max_decision_calls_per_model


def budget_snapshot() -> dict[str, Any]:
    with _lock:
        b = _read_json(budget_path(), {})
    return {
        "total": b.get("total", 0),
        "per_model": b.get("per_model", {}),
        "limits": {
            "total": SETTINGS.max_total_api_calls,
            "claude": SETTINGS.max_claude_calls,
            "per_decision_model": SETTINGS.max_decision_calls_per_model,
            "key_hard_limit": SETTINGS.key_hard_limit,
        },
        "cost_usd": round(b.get("cost_usd", 0.0), 6),
        "updated_at": b.get("updated_at"),
    }


def reserve(model_id: str, category: str) -> dict[str, int]:
    """Count one actual request attempt for model_id, or raise BudgetExceeded.

    Re-reads the file under the lock each time, so the CLI and the server can never
    double-spend the budget between them."""
    with _lock:
        b = _read_json(budget_path(), {})
        total = b.get("total", 0)
        per = b.setdefault("per_model", {})
        used = per.get(model_id, 0)
        lim = limit_for(category)
        if total >= SETTINGS.max_total_api_calls:
            raise BudgetExceeded(f"total API budget used ({total}/{SETTINGS.max_total_api_calls})")
        if used >= lim:
            raise BudgetExceeded(f"{model_id} budget used ({used}/{lim})")
        b["total"] = total + 1
        per[model_id] = used + 1
        b["updated_at"] = time.time()
        _write_json(budget_path(), b)
        return {"total": b["total"], "model": per[model_id]}


def add_cost(usd: float) -> None:
    if not usd:
        return
    with _lock:
        b = _read_json(budget_path(), {})
        b["cost_usd"] = b.get("cost_usd", 0.0) + float(usd)
        _write_json(budget_path(), b)


def remaining(model_id: str, category: str) -> int:
    snap = budget_snapshot()
    return max(0, min(SETTINGS.max_total_api_calls - snap["total"],
                      limit_for(category) - snap["per_model"].get(model_id, 0)))


# ------------------------------------------------------------------------- cache
def cache_key(provider: str, endpoint: str, payload: dict[str, Any]) -> str:
    canon = json.dumps({"p": provider, "e": endpoint, "body": payload}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()


def cache_get(key: str) -> dict[str, Any] | None:
    with _lock:
        return _read_json(cache_path(), {}).get(key)


def cache_put(key: str, entry: dict[str, Any]) -> None:
    with _lock:
        c = _read_json(cache_path(), {})
        c[key] = entry
        _write_json(cache_path(), c)


def cache_size() -> int:
    with _lock:
        return len(_read_json(cache_path(), {}))


# --------------------------------------------------------------------------- log
def log(event: dict[str, Any]) -> None:
    event = {"ts": round(time.time(), 3), **event}
    with _lock:
        p = log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
