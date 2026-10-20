import asyncio

from app import adapters
from app.adapters import (
    MockAdapter, Observation, chat_payload, decisions_payload, parse_chat_content,
    parse_decisions_response,
)
from app.config import MODELS_BY_KEY
from app.cube import MOVES, SOLVED, apply_moves, is_valid_move


def obs():
    return Observation(apply_moves(SOLVED, ["R", "U"]), ["R", "U"], 2, 30)


def test_decisions_payload_identical_except_model():
    a = decisions_payload(MODELS_BY_KEY["jev"], obs())
    b = decisions_payload(MODELS_BY_KEY["clef"], obs())
    assert a["model"] != b["model"]
    a.pop("model"), b.pop("model")
    assert a == b
    q = a["questions"]["next_move"]
    assert q["type"] == "choice" and set(q["criteria"]) == set(MOVES)
    assert a["state"]["cube_facelets"] == obs().state


def test_chat_payload_shares_state_and_options():
    p = chat_payload(MODELS_BY_KEY["opus"], obs())
    schema = p["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["move"]["enum"] == MOVES
    assert '"cube_facelets"' in p["messages"][1]["content"]


def test_parse_decisions_response():
    body = {"answers": {"next_move": {"type": "choice", "choice": "R'", "confidence": 0.7,
                                      "probabilities": {"R'": 0.8}}}}
    move, err, conf, probs = parse_decisions_response(body)
    assert (move, err, conf) == ("R'", None, 0.7) and probs == {"R'": 0.8}
    assert parse_decisions_response({"answers": {}})[0] is None
    move, err, *_ = parse_decisions_response({"answers": {"next_move": {"choice": "X9"}}})
    assert move is None and "invalid" in err


def test_parse_chat_is_strict():
    assert parse_chat_content('{"move": "F2"}') == ("F2", None)
    for bad in ["", "R'", '```json\n{"move": "R"}\n```', '{"mv": "R"}', '{"move": "R3"}', "[1]"]:
        move, err = parse_chat_content(bad)
        assert move is None and err


def test_mock_adapter_returns_legal_moves():
    adapters.SETTINGS = adapters.SETTINGS.__class__(mock_latency_scale=0.0)
    ad = MockAdapter(MODELS_BY_KEY["jev"], seed=1)
    d = asyncio.run(ad.decide(obs()))
    assert d.move is not None and is_valid_move(d.move) and d.error is None
    assert d.confidence is not None
