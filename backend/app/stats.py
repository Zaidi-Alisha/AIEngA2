"""Aggregate benchmark statistics (section 3C / section 7 of the assignment)."""

from __future__ import annotations

import statistics
from typing import Any, Iterable

from .config import MODELS, MODELS_BY_KEY, TEST_SETS


def _mean(xs: list[float]) -> float | None:
    return round(statistics.fmean(xs), 3) if xs else None


def _median(xs: list[float]) -> float | None:
    return round(statistics.median(xs), 3) if xs else None


def aggregate(runs: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """runs: serialised Run dicts. Returns per test set -> per model metrics, plus overall."""
    buckets: dict[str, dict[str, list[tuple[dict, dict]]]] = {}
    for run in runs:
        for p in run["puzzles"]:
            if p.get("status") != "done":
                continue
            for key, t in p["trials"].items():
                if t["status"] in ("pending", "running", "cancelled"):
                    continue
                buckets.setdefault(p["test_set"], {}).setdefault(key, []).append((p, t))
                buckets.setdefault("all", {}).setdefault(key, []).append((p, t))

    out: dict[str, Any] = {}
    for set_name, per_model in buckets.items():
        rows = []
        for spec in MODELS:
            items = per_model.get(spec.key)
            if not items:
                continue
            rows.append(_model_row(spec.key, items))
        out[set_name] = {
            "label": TEST_SETS.get(set_name, {}).get("label", "All test sets"),
            "puzzles": len({(id(p), p["index"], p["state"]) for items in per_model.values() for p, _ in items}),
            "models": rows,
            "answers": _answers(rows),
        }
    return out


def _model_row(key: str, items: list[tuple[dict, dict]]) -> dict[str, Any]:
    spec = MODELS_BY_KEY[key]
    trials = [t for _, t in items]
    latencies = [ms for t in trials for ms in t["call_latencies_ms"]]
    solved = [(p, t) for p, t in items if t["status"] == "solved"]
    gaps = [t["move_count"] - p["optimal_moves"] for p, t in solved if p.get("optimal_moves") is not None]
    statuses: dict[str, int] = {}
    for t in trials:
        statuses[t["status"]] = statuses.get(t["status"], 0) + 1
    calls = len(latencies)
    invalid = sum(len(t["invalid"]) for t in trials)
    return {
        "model": key,
        "name": spec.name,
        "category": spec.category,
        "model_id": spec.model_id,
        "trials": len(trials),
        "solved": len(solved),
        "success_rate": round(100 * len(solved) / len(trials), 1),
        "avg_latency_ms": _mean(latencies),
        "median_latency_ms": _median(latencies),
        "avg_total_time_s": _mean([t["total_time_s"] for t in trials if t["total_time_s"] is not None]),
        "avg_solve_time_s": _mean([t["total_time_s"] for _, t in solved]),
        "total_moves": sum(t["move_count"] for t in trials),
        "avg_moves": _mean([t["move_count"] for t in trials]),
        "avg_moves_solved": _mean([t["move_count"] for _, t in solved]),
        "avg_optimal_moves": _mean([p["optimal_moves"] for p, _ in items if p.get("optimal_moves") is not None]),
        "avg_optimal_gap": _mean(gaps),
        "optimal_solves": sum(1 for g in gaps if g == 0),
        "gap_samples": len(gaps),
        "avg_cube_completion_pct": _mean([100 * (t.get("correct_stickers") or 0) / 54 for t in trials]),
        "invalid_outputs": invalid,
        "invalid_rate_pct": round(100 * invalid / calls, 2) if calls else 0.0,
        "retries": sum(t["retries"] for t in trials),
        "api_calls": calls,
        "avg_confidence": _mean([m["confidence"] for t in trials for m in t["moves"]
                                 if m.get("confidence") is not None]),
        "statuses": statuses,
        "cost_usd": round(sum(t.get("cost_usd") or 0 for t in trials), 6),
        "live_api_calls": sum(t.get("api_calls") or 0 for t in trials),
        "cache_hits": sum(t.get("cache_hits") or 0 for t in trials),
        "avg_live_latency_ms": _mean([ms for t in trials for ms in (t.get("live_latencies_ms") or [])]),
        "avg_cache_served_ms": _mean([ms for t in trials for ms in (t.get("cache_served_ms") or [])]),
    }


def _answers(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Machine answers to the five questions in section 8.

    Each question names the leader on its own metric; *_tied lists every model that
    shares the leading value, so ties are reported as ties instead of an arbitrary pick.
    """
    if not rows:
        return {}
    with_lat = [r for r in rows if r["avg_latency_ms"] is not None]
    fastest = min(with_lat, key=lambda r: r["avg_latency_ms"]) if with_lat else None
    top_rate = max(r["success_rate"] for r in rows)
    rate_tied = [r["model"] for r in rows if r["success_rate"] == top_rate] if top_rate > 0 else []
    # Among equal solve rates, fewer moves on solved puzzles is the better result.
    best_rate = max(rows, key=lambda r: (r["success_rate"], -(r["avg_moves_solved"] or 1e9))) if top_rate > 0 else None
    with_gap = [r for r in rows if r["avg_optimal_gap"] is not None]
    top_gap = min((r["avg_optimal_gap"] for r in with_gap), default=None)
    gap_tied = [r["model"] for r in with_gap if r["avg_optimal_gap"] == top_gap]
    best_gap = min(with_gap, key=lambda r: (r["avg_optimal_gap"], -r["success_rate"])) if with_gap else None
    f = fastest["model"] if fastest else None
    return {
        "fastest": f,
        "highest_solve_rate": best_rate["model"] if best_rate else None,
        "highest_solve_rate_tied": rate_tied,
        "shortest_solutions": best_gap["model"] if best_gap else None,
        "shortest_solutions_tied": gap_tied,
        "fastest_is_best_quality": bool(f and f in rate_tied and f in gap_tied),
    }
