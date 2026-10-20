"""The single request path: cache -> budget -> HTTP -> log, incl. failures and replays."""
import asyncio
import dataclasses

import httpx
import pytest

from app import adapters, ledger
from app.adapters import BudgetStop, CachedError, DecisionsAdapter, Observation, TransportError
from app.config import MODELS_BY_KEY
from app.cube import SOLVED, apply_moves


def obs():
    return Observation(apply_moves(SOLVED, ["R", "U"]), ["R", "U"], 2, 20)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    s = dataclasses.replace(
        ledger.SETTINGS, api_key="sk-or-v1-test", budget_file=str(tmp_path / "b.json"),
        cache_file=str(tmp_path / "c.json"), api_log_file=str(tmp_path / "l.jsonl"),
        max_total_api_calls=10, max_decision_calls_per_model=3, max_retries=1, cache_only=False)
    monkeypatch.setattr(ledger, "SETTINGS", s)
    monkeypatch.setattr(adapters, "SETTINGS", s)
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    return s


async def _no_sleep(_):
    return None


def adapter(handler):
    ad = DecisionsAdapter(MODELS_BY_KEY["jev"])
    ad.client = httpx.AsyncClient(base_url="http://test", transport=httpx.MockTransport(handler))
    return ad


def ok_body(choice="U'"):
    return {"answers": {"next_move": {"type": "choice", "choice": choice, "confidence": 0.5}},
            "usage": {"input_tokens": 10, "output_tokens": 2, "cost": 0.001}}


def test_success_is_cached_and_replayed_for_free(env):
    calls = []
    a = adapter(lambda req: calls.append(1) or httpx.Response(200, json=ok_body()))
    d1 = asyncio.run(a.decide(obs()))
    assert (d1.move, d1.source, d1.api_calls) == ("U'", "live", 1)
    b = adapter(lambda req: calls.append(1) or httpx.Response(500))  # would fail if called
    d2 = asyncio.run(b.decide(obs()))
    assert (d2.move, d2.source, d2.api_calls) == ("U'", "cache", 0)
    assert len(calls) == 1
    assert ledger.budget_snapshot()["total"] == 1
    assert ledger.budget_snapshot()["cost_usd"] == pytest.approx(0.001)


def test_retries_count_against_budget_and_failures_replay_without_requests(env):
    calls = []
    a = adapter(lambda req: calls.append(1) or httpx.Response(502, json={"error": {"message": "refused"}}))
    with pytest.raises(TransportError) as e:
        asyncio.run(a.decide(obs()))
    assert e.value.api_calls == 2 and e.value.retries == 1  # first try + 1 retry
    assert ledger.budget_snapshot()["total"] == 2
    b = adapter(lambda req: calls.append(1) or httpx.Response(200, json=ok_body()))
    with pytest.raises(CachedError):
        asyncio.run(b.decide(obs()))           # same request: the cached failure, no call
    assert len(calls) == 2 and ledger.budget_snapshot()["total"] == 2


def test_budget_blocks_before_sending(env):
    calls = []
    a = adapter(lambda req: calls.append(1) or httpx.Response(200, json=ok_body()))
    for i in range(3):                          # per-model cap is 3
        asyncio.run(a.decide(Observation(apply_moves(SOLVED, ["R"] * (i + 1)), [], 0, 20)))
    with pytest.raises(BudgetStop):
        asyncio.run(a.decide(Observation(apply_moves(SOLVED, ["F"]), [], 0, 20)))
    assert len(calls) == 3


def test_cache_only_never_sends(env, monkeypatch):
    s = dataclasses.replace(env, cache_only=True)
    monkeypatch.setattr(adapters, "SETTINGS", s)
    calls = []
    a = adapter(lambda req: calls.append(1) or httpx.Response(200, json=ok_body()))
    with pytest.raises(BudgetStop):
        asyncio.run(a.decide(obs()))
    assert calls == [] and ledger.budget_snapshot()["total"] == 0
