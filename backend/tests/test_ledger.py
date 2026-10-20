import dataclasses

import pytest

from app import ledger


@pytest.fixture(autouse=True)
def tmp_state(tmp_path, monkeypatch):
    s = dataclasses.replace(
        ledger.SETTINGS, budget_file=str(tmp_path / "b.json"), cache_file=str(tmp_path / "c.json"),
        api_log_file=str(tmp_path / "l.jsonl"), max_total_api_calls=7, max_claude_calls=2,
        max_decision_calls_per_model=3)
    monkeypatch.setattr(ledger, "SETTINGS", s)
    return tmp_path


def test_per_model_and_total_caps():
    for _ in range(2):
        ledger.reserve("claude", "llm")
    with pytest.raises(ledger.BudgetExceeded):
        ledger.reserve("claude", "llm")          # Claude cap (2)
    for _ in range(3):
        ledger.reserve("jev", "decision")
    with pytest.raises(ledger.BudgetExceeded):
        ledger.reserve("jev", "decision")        # per decision model cap (3)
    ledger.reserve("clef", "decision")
    ledger.reserve("clef", "decision")           # total now 7
    with pytest.raises(ledger.BudgetExceeded):
        ledger.reserve("luna", "decision")       # total cap (7)
    snap = ledger.budget_snapshot()
    assert snap["total"] == 7 and snap["per_model"] == {"claude": 2, "jev": 3, "clef": 2}


def test_counter_is_persisted_and_survives_reload(tmp_state):
    ledger.reserve("jev", "decision")
    # A "restart" is just a fresh read of the file: nothing is held only in memory.
    assert ledger._read_json(ledger.budget_path(), {})["total"] == 1
    ledger.reserve("jev", "decision")
    assert ledger.budget_snapshot()["per_model"]["jev"] == 2
    assert ledger.remaining("jev", "decision") == 1


def test_cache_roundtrip_and_key_stability():
    k1 = ledger.cache_key("live", "/x", {"a": 1, "b": [1, 2]})
    k2 = ledger.cache_key("live", "/x", {"b": [1, 2], "a": 1})
    assert k1 == k2 != ledger.cache_key("ollama", "/x", {"a": 1, "b": [1, 2]})
    assert ledger.cache_get(k1) is None
    ledger.cache_put(k1, {"body": {"ok": 1}, "live_latency_ms": 12.5})
    assert ledger.cache_get(k1)["body"] == {"ok": 1}
    assert ledger.cache_size() == 1
