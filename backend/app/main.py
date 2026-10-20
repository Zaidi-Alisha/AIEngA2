"""FastAPI backend for the Rubik's Cube Race.

Run from the project root:  uvicorn app.main:app --app-dir backend --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import cube, ledger, solver
from .config import FRONTEND_DIR, MODELS, OLLAMA_MODELS, PROVIDERS, SETTINGS, TEST_SETS
from .race import RunManager, create_run, load_saved_runs
from .stats import aggregate

@asynccontextmanager
async def lifespan(_app: FastAPI):
    solver.warm_up()  # build the BFS table once, before the first request
    yield


app = FastAPI(title="Rubik's Cube Race", version="1.0.0", lifespan=lifespan)
manager = RunManager()


class RunRequest(BaseModel):
    test_set: str = "primary"
    puzzles: int = Field(5, ge=1, le=50)
    seed: Optional[int] = None
    models: Optional[list[str]] = None
    provider: str = "mock"


def _ollama_models() -> list[str] | None:
    """Installed Ollama models, or None if Ollama is not running."""
    try:
        r = httpx.get(f"{SETTINGS.ollama_url}/api/tags", timeout=1.5)
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return None


def _saved_runs() -> list[dict]:
    """Saved runs. A run left unfinished by a previous server process (stopped server,
    crash) is marked interrupted, together with its unfinished puzzles and trials."""
    out = []
    for r in load_saved_runs():
        if r["id"] not in manager.runs and r["status"] in ("pending", "running"):
            r["status"] = "interrupted"
            for p in r["puzzles"]:
                if p["status"] in ("pending", "running"):
                    p["status"] = "interrupted"
                    for t in p["trials"].values():
                        if t["status"] in ("pending", "running"):
                            t["status"] = "interrupted"
                            t["phase"] = ""
        out.append(r)
    return out


@app.get("/api/config")
def get_config():
    # Note: deliberately exposes only whether a key is configured, never the key itself.
    return {
        "mode": "mock" if SETTINGS.mock_mode else "live",
        "providers": _providers(),
        "budget": ledger.budget_snapshot(),
        "student": {"name": SETTINGS.student_name, "roll": SETTINGS.student_roll},
        "limits": {
            "max_moves": SETTINGS.max_moves,
            "request_timeout_s": SETTINGS.request_timeout_s,
            "max_retries": SETTINGS.max_retries,
            "max_invalid_outputs": SETTINGS.max_invalid,
            "trial_time_limit_s": SETTINGS.trial_time_limit_s,
            "recent_moves_window": SETTINGS.recent_moves_window,
        },
        "test_sets": TEST_SETS,
        "models": [
            {"key": m.key, "name": m.name, "category": m.category, "model_id": m.model_id,
             "interface": m.interface, "color": m.color, "ollama_model": OLLAMA_MODELS[m.key]}
            for m in MODELS
        ],
        "moves": cube.MOVES,
        "solved": cube.SOLVED,
    }


def _providers() -> list[dict]:
    installed = _ollama_models()
    out = []
    for key, label in PROVIDERS.items():
        if key == "live":
            ok, why = (not SETTINGS.mock_mode), ("" if not SETTINGS.mock_mode else "no OPENROUTER_API_KEY")
        elif key == "ollama":
            missing = [m for m in OLLAMA_MODELS.values() if installed is not None and m not in installed
                       and f"{m}:latest" not in installed]
            ok = installed is not None and not missing
            why = "Ollama not running" if installed is None else (f"missing models: {', '.join(missing)}" if missing else "")
        else:
            ok, why = True, ""
        out.append({"key": key, "label": label, "available": ok, "reason": why})
    return out


@app.get("/api/budget")
def get_budget():
    snap = ledger.budget_snapshot()
    snap["cache_entries"] = ledger.cache_size()
    return snap


@app.post("/api/runs")
async def start_run(req: RunRequest):
    busy = manager.active()
    if busy is not None:
        # One run at a time: concurrent runs would share the network/CPU and skew latency.
        raise HTTPException(409, f"Run {busy.id} is still in progress. Stop it or wait for it to finish.")
    try:
        run = create_run(req.test_set, req.puzzles, req.seed, req.models, req.provider)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    manager.start(run)
    return run.to_dict()


@app.get("/api/runs")
def list_runs():
    live = {rid: r.to_dict() for rid, r in manager.runs.items()}
    saved = {r["id"]: r for r in _saved_runs()}
    saved.update(live)
    rows = sorted(saved.values(), key=lambda r: r["created_at"], reverse=True)
    return [
        {k: r[k] for k in ("id", "test_set", "seed", "mode", "status", "created_at", "models")}
        | {"puzzles": len(r["puzzles"])}
        for r in rows
    ]


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    if run_id in manager.runs:
        return manager.runs[run_id].to_dict()
    for r in _saved_runs():
        if r["id"] == run_id:
            return r
    raise HTTPException(404, "run not found")


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    if not manager.cancel(run_id):
        raise HTTPException(404, "run not active")
    return {"ok": True}


@app.get("/api/stats")
def get_stats(run_id: Optional[str] = None, mode: Optional[str] = None):
    """Aggregate statistics. run_id limits to one run; mode filters mock/live runs."""
    runs = {r["id"]: r for r in _saved_runs()}
    runs.update({rid: r.to_dict() for rid, r in manager.runs.items()})
    selected = list(runs.values())
    if run_id:
        selected = [r for r in selected if r["id"] == run_id]
    else:  # cache replays duplicate an earlier run's data: count the original only
        selected = [r for r in selected if not r.get("settings", {}).get("replay_from_cache")]
    if mode:
        selected = [r for r in selected if r["mode"] == mode]
    return {"runs": len(selected), "sets": aggregate(selected)}


@app.get("/api/solve")
def solve(state: str):
    """Debug helper: exact shortest solution for a facelet string (<= 8 moves)."""
    if len(state) != 54:
        raise HTTPException(400, "state must be 54 characters")
    sol = solver.optimal_solution(state)
    return {"solved": cube.is_solved(state), "optimal": list(sol) if sol is not None else None}


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")
