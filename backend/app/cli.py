"""Headless benchmark + report generator.

Examples (from the project root):
    python backend/run_benchmark.py run --set warmup --puzzles 3 --seed 1
    python backend/run_benchmark.py run --set primary --puzzles 10 --seed 42
    python backend/run_benchmark.py run --set extension --puzzles 3 --seed 7
    python backend/run_benchmark.py report            # rewrites results/RESULTS.md + README section
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time

from . import race
from .config import MODELS_BY_KEY, ROOT, SETTINGS, TEST_SETS
from .stats import aggregate

START, END = "<!-- RESULTS:START -->", "<!-- RESULTS:END -->"


def _fmt(v, suffix="", nd=2):
    if v is None:
        return "–"
    if isinstance(v, float):
        return f"{v:.{nd}f}{suffix}"
    return f"{v}{suffix}"


def _secs(v):
    if v is None:
        return "–"
    return f"{v:.2f} s" if v < 60 else f"{int(v // 60)}:{v % 60:05.2f} min"


def _name(key):
    return MODELS_BY_KEY[key].name if key in MODELS_BY_KEY else "–"


def _names(keys):
    """Leader, or 'tie: A & B' when several models share the leading value."""
    if not keys:
        return "–"
    names = " & ".join(_name(k) for k in keys)
    return f"tie: {names}" if len(keys) > 1 else names


def build_report(runs: list[dict], mode: str = "mock") -> str:
    stats = aggregate(runs)
    lines = []
    banner = {
        "live": "> **Live OpenRouter runs** — real API calls, budget-capped (see the API budget table).",
        "ollama": "> **Ollama runs** — real local open models standing in for each slot (free, no API budget).",
        "mock": "> **Mock runs** — simulated models, no API calls. These only verify the pipeline.",
    }.get(mode, "")
    lines += [banner, ""]
    lines.append(f"Runs included: **{len(runs)}** · generated {time.strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    order = [s for s in ("live3", "primary", "warmup", "extension", "all") if s in stats]
    if len([s for s in order if s != "all"]) <= 1:
        order = [s for s in order if s != "all"]  # "all" would just repeat the only set
    model_ids = runs[0]["settings"].get("model_ids", {}) if runs else {}
    for set_name in order:
        block = stats[set_name]
        rng = TEST_SETS.get(set_name)
        if rng and rng.get("exact_optimal"):
            label = block["label"] + " — exactly " + str(rng["exact_optimal"]) + " moves from solved (BFS-verified)"
        else:
            label = block["label"] + (f" ({rng['min']}–{rng['max']} scramble turns)" if rng else "")
        n = block["puzzles"]
        lines += [f"#### {label} — {n} puzzle{'' if n == 1 else 's'}", ""]
        lines.append("| Model | Type | Trials | Solved | Success rate | Avg latency / move | "
                     "Avg total time | Total moves | Avg moves (solved) | Avg optimal | "
                     "Optimal gap | Gap = 0 | Cube completion | Invalid outputs | Retries | "
                     "API calls | Cache hits | Cost (USD) |")
        lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for r in block["models"]:
            name = r["name"] if mode != "ollama" else f"{r['name']} slot → `{model_ids.get(r['model'], '?')}`"
            lines.append(
                f"| {name} | {'Decision' if r['category'] == 'decision' else 'Frontier LLM'} "
                f"| {r['trials']} | {r['solved']} | {r['success_rate']:.0f}% "
                f"| {_fmt(r['avg_latency_ms'], ' ms', 0)} | {_secs(r['avg_total_time_s'])} "
                f"| {r['total_moves']} | {_fmt(r['avg_moves_solved'])} | {_fmt(r['avg_optimal_moves'])} "
                f"| {_fmt(r['avg_optimal_gap'], nd=2) if r['avg_optimal_gap'] is not None else '–'} "
                f"| {r['optimal_solves']}/{r['gap_samples']} | {_fmt(r['avg_cube_completion_pct'], '%', 1)} "
                f"| {r['invalid_outputs']} | {r['retries']} "
                f"| {r.get('live_api_calls', 0)} | {r.get('cache_hits', 0)} | {r.get('cost_usd', 0):.6f} |"
            )
        a = block["answers"]
        lines += ["", f"Fastest decisions: **{_name(a.get('fastest'))}** · "
                      f"highest solve rate: **{_names(a.get('highest_solve_rate_tied'))}** · "
                      f"shortest solutions: **{_names(a.get('shortest_solutions_tied'))}**", ""]
    # Per-puzzle detail for the primary set (or whatever exists).
    lines += ["#### Per-puzzle results", "",
              "| Run | Set | # | Scramble | Optimal | " +
              " | ".join(_name(k) for k in MODELS_BY_KEY) + " |",
              "|---|---|---:|---|---:|" + "---|" * len(MODELS_BY_KEY)]
    for r in runs:
        for p in r["puzzles"]:
            if p["status"] != "done":
                continue
            cells = []
            for k in MODELS_BY_KEY:
                t = p["trials"].get(k)
                if not t:
                    cells.append("–")
                    continue
                mark = "✅" if t["status"] == "solved" else "❌"
                cells.append(f"{mark} {t['move_count']} mv, {_secs(t['total_time_s'])}"
                             + ("" if t["status"] == "solved" else f" ({t['status']})"))
            lines.append(f"| `{r['id']}` | {p['test_set']} | {p['index'] + 1} | `{' '.join(p['scramble'])}` "
                         f"| {_fmt(p['optimal_moves'])} | " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def write_report() -> str:
    from . import ledger

    runs = race.load_saved_runs()
    if not runs:
        print("No saved runs in results/. Run a benchmark first.", file=sys.stderr)
        return ""
    parts = []
    titles = {"live": "### 6.1 Live OpenRouter experiment", "ollama": "### 6.2 Ollama experiments (local open models)",
              "mock": "### 6.3 Mock runs (pipeline verification only)"}
    for mode in ("live", "ollama", "mock"):
        sel = [r for r in runs if r["mode"] == mode and any(p["status"] == "done" for p in r["puzzles"])
               and not r.get("settings", {}).get("replay_from_cache")]
        if sel:
            parts.append(titles[mode] + "\n\n" + build_report(sel, mode))
    b = ledger.budget_snapshot()
    lim = b["limits"]
    rows = "\n".join(f"| `{m}` | {n} |" for m, n in sorted(b["per_model"].items()))
    parts.append(
        "### 6.4 OpenRouter API budget (persistent counter, all attempts incl. retries/failures)\n\n"
        f"Total actual requests: **{b['total']} / {lim['total']}** (key hard limit {lim['key_hard_limit']}) · "
        f"Claude limit {lim['claude']} · decision-model limit {lim['per_decision_model']} each · "
        f"actual cost reported by OpenRouter: **${b['cost_usd']:.6f}** · cached responses: {ledger.cache_size()}\n\n"
        "| Model | Actual requests |\n|---|---:|\n" + (rows or "| – | 0 |") + "\n"
    )
    report = f"Generated {time.strftime('%Y-%m-%d %H:%M')} from `results/run-*.json` and `state/`.\n\n" + "\n\n".join(parts)
    (ROOT / "results" / "RESULTS.md").write_text("# Benchmark results\n\n" + report, encoding="utf-8")
    readme = ROOT / "README.md"
    if readme.exists():
        text = readme.read_text(encoding="utf-8")
        if START in text and END in text:
            text = re.sub(re.escape(START) + r".*?" + re.escape(END),
                          lambda _: f"{START}\n{report}\n{END}", text, flags=re.S)
            readme.write_text(text, encoding="utf-8")
    return report


def _progress(run, puzzle):
    cells = []
    for k, t in puzzle.trials.items():
        cells.append(f"{k}:{t.status}/{t.move_count}mv/{t.total_time_s:.1f}s")
    print(f"  puzzle {puzzle.index + 1}/{len(run.puzzles)} "
          f"[{' '.join(puzzle.scramble)}] opt={puzzle.optimal_moves} -> " + "  ".join(cells), flush=True)


async def _check(provider: str, models: list[str] | None):
    from . import cube
    from .adapters import Observation, make_adapter
    from .config import MODELS

    state = cube.apply_moves(cube.SOLVED, ["R", "U"])
    print(f"provider={provider} | test state = solved + R U (optimal answer: U')")
    for spec in MODELS:
        if models and spec.key not in models:
            continue
        ad = make_adapter(spec, seed=0, provider=provider)
        try:
            d = await ad.decide(Observation(state, ["R", "U"], 2, SETTINGS.max_moves))
            print(f"  OK   {spec.name:<22} {getattr(ad, 'model_id', spec.model_id):<32} move={d.move} err={d.error} "
                  f"source={d.source} api_calls={d.api_calls} latency={d.latency_ms:.0f}ms conf={d.confidence} raw={d.raw[:120]}")
        except Exception as exc:
            print(f"  FAIL {spec.name:<22} {spec.model_id:<32} {exc}")
        finally:
            await ad.aclose()


async def _preflight(test_set: str, seed: int, provider: str, models: list[str]):
    """Send each model ONLY the first move of the exact puzzle the run will use. The
    answer is cached, so the real run reuses it for free; a format error costs one call
    instead of a whole run."""
    from .adapters import Observation, make_adapter
    from .config import MODELS_BY_KEY

    puzzle = race.make_puzzles(test_set, 1, seed)[0]
    print(f"puzzle: scramble {' '.join(puzzle.scramble)} | optimal {puzzle.optimal_moves} {puzzle.optimal_solution}")
    for key in models:
        spec = MODELS_BY_KEY[key]
        ad = make_adapter(spec, seed=seed * 1000, provider=provider)
        try:
            d = await ad.decide(Observation(puzzle.state, [], 0, SETTINGS.max_moves))
            print(f"  OK   {spec.name:<22} move={d.move} err={d.error} source={d.source} api_calls={d.api_calls} "
                  f"latency={d.latency_ms:.0f}ms conf={d.confidence} cost={d.usage.get('cost')} raw={d.raw[:160]}")
        except Exception as exc:
            print(f"  FAIL {spec.name:<22} {type(exc).__name__}: {exc}")
        finally:
            await ad.aclose()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Rubik's Cube Race benchmark")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a benchmark")
    r.add_argument("--set", default="primary", choices=list(TEST_SETS))
    r.add_argument("--puzzles", type=int, default=None)
    r.add_argument("--seed", type=int, default=None)
    r.add_argument("--models", default=None, help="comma separated keys, e.g. jev,opus")
    r.add_argument("--no-report", action="store_true")
    r.add_argument("--provider", default="mock", choices=["mock", "ollama", "live"])
    r.add_argument("--yes-spend-budget", action="store_true",
                   help="required for --provider live: confirms real, budget-capped OpenRouter calls")
    sub.add_parser("report", help="regenerate results/RESULTS.md and the README results section")
    c = sub.add_parser("check", help="send one request per model to verify IDs and parsing")
    c.add_argument("--provider", default="mock", choices=["mock", "ollama", "live"])
    c.add_argument("--models", default=None)
    c.add_argument("--yes-spend-budget", action="store_true")
    sub.add_parser("budget", help="show the persistent OpenRouter request counters")
    pf = sub.add_parser("preflight", help="first move only, for the exact puzzle a run will use (cached)")
    pf.add_argument("--set", default="live3", choices=list(TEST_SETS))
    pf.add_argument("--seed", type=int, required=True)
    pf.add_argument("--provider", default="mock", choices=["mock", "ollama", "live"])
    pf.add_argument("--models", default="jev,luna,clef")
    pf.add_argument("--yes-spend-budget", action="store_true")
    args = ap.parse_args(argv)

    if getattr(args, "provider", None) == "live" and not args.yes_spend_budget:
        from . import ledger
        print("Refusing: --provider live makes real OpenRouter calls that count against the key's "
              "hard limit. Budget now:", ledger.budget_snapshot(), "\nRe-run with --yes-spend-budget.")
        return
    if args.cmd == "budget":
        from . import ledger
        print(json.dumps(ledger.budget_snapshot() | {"cache_entries": ledger.cache_size()}, indent=1))
    elif args.cmd == "preflight":
        asyncio.run(_preflight(args.set, args.seed, args.provider, args.models.split(",")))
        from . import ledger
        print("budget:", ledger.budget_snapshot())
    elif args.cmd == "check":
        asyncio.run(_check(args.provider, args.models.split(",") if args.models else None))
    elif args.cmd == "run":
        count = args.puzzles or TEST_SETS[args.set]["default_puzzles"]
        models = args.models.split(",") if args.models else None
        run = race.create_run(args.set, count, args.seed, models, args.provider)
        print(f"Run {run.id} | set={args.set} | puzzles={count} | seed={run.seed} | provider={run.mode}")
        asyncio.run(race.execute_run(run, on_update=_progress))
        print(f"Saved results/run-{run.id}.json")
        if not args.no_report:
            write_report()
            print("Updated results/RESULTS.md and README.md")
    else:
        print(write_report())


if __name__ == "__main__":
    main()
