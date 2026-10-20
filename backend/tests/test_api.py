import dataclasses
import time

import pytest
from fastapi.testclient import TestClient

from app import adapters, main, race


@pytest.fixture()
def client(tmp_path, monkeypatch):
    fast = dataclasses.replace(race.SETTINGS, api_key="mock", mock_latency_scale=0.05, puzzle_pause_s=0.0)
    monkeypatch.setattr(race, "SETTINGS", fast)
    monkeypatch.setattr(adapters, "SETTINGS", fast)
    monkeypatch.setattr(race, "RESULTS_DIR", tmp_path)  # never write into the real results/
    monkeypatch.setattr(main, "manager", race.RunManager())
    with TestClient(main.app) as c:
        yield c


def wait_for(c, run_id, statuses, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = c.get(f"/api/runs/{run_id}").json()
        if r["status"] in statuses:
            return r
        time.sleep(0.1)
    raise AssertionError(f"run never reached {statuses}")


def test_run_is_running_immediately_and_completes(client, tmp_path):
    r = client.post("/api/runs", json={"test_set": "warmup", "puzzles": 1, "seed": 3})
    assert r.status_code == 200
    run = r.json()
    assert run["status"] == "running"  # the UI polls only while pending/running
    assert (tmp_path / f"run-{run['id']}.json").exists()  # saved before the first puzzle ends
    done = wait_for(client, run["id"], {"done"})
    p = done["puzzles"][0]
    assert p["status"] == "done"
    assert sorted(t["rank"] for t in p["trials"].values()) == [1, 2, 3, 4]
    stats = client.get(f"/api/stats?run_id={run['id']}").json()
    assert stats["sets"]["warmup"]["models"]


def test_second_run_is_rejected_while_one_is_active(client):
    first = client.post("/api/runs", json={"test_set": "primary", "puzzles": 3, "seed": 1}).json()
    second = client.post("/api/runs", json={"test_set": "primary", "puzzles": 1, "seed": 2})
    assert second.status_code == 409
    client.post(f"/api/runs/{first['id']}/cancel")
    wait_for(client, first["id"], {"cancelled"})


def test_stop_takes_effect_quickly_and_unfinished_puzzles_are_not_counted(client):
    run = client.post("/api/runs", json={"test_set": "extension", "puzzles": 2, "seed": 7}).json()
    time.sleep(0.5)
    t0 = time.time()
    client.post(f"/api/runs/{run['id']}/cancel")
    stopped = wait_for(client, run["id"], {"cancelled"}, timeout=10)
    assert time.time() - t0 < 5
    assert all(p["status"] == "cancelled" for p in stopped["puzzles"])
    assert all(t["rank"] is None for p in stopped["puzzles"] for t in p["trials"].values())
    stats = client.get(f"/api/stats?run_id={run['id']}").json()
    assert stats["sets"] == {}


def test_bad_input_is_rejected(client):
    assert client.post("/api/runs", json={"test_set": "nope", "puzzles": 1}).status_code == 400
    assert client.post("/api/runs", json={"test_set": "warmup", "puzzles": 0}).status_code == 422
    assert client.post("/api/runs", json={"test_set": "warmup", "puzzles": 2.5}).status_code == 422
