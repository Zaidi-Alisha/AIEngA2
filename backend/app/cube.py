"""Deterministic 3x3 Rubik's Cube engine.

State representation
--------------------
A cube is a 54-character facelet string in the standard (Kociemba) order:

    U1..U9  R1..R9  F1..F9  D1..D9  L1..L9  B1..B9

Each face is read row by row as seen when looking straight at that face, with:
    U: B edge on top        R: U on top, F on the left     F: U on top
    D: F edge on top        L: U on top, B on the left     B: U on top, R on the left

Each character is the face letter (U/R/F/D/L/B) of the colour sitting there, so the
solved cube is "UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB".

Moves
-----
The 18 face moves of the half-turn metric (HTM): X, X' and X2 for X in U R F D L B.
Every move is precomputed as a permutation of the 54 sticker indices by rotating
each sticker's 3D position/normal, so the engine cannot drift from the geometry.
"""

from __future__ import annotations

import random
from typing import Iterable

FACES = "URFDLB"
SOLVED = "".join(f * 9 for f in FACES)
MOVES: list[str] = [f + s for f in FACES for s in ("", "'", "2")]

# Outward normal of each face, in a right-handed frame: x -> R, y -> U, z -> F.
_NORMALS = {
    "U": (0, 1, 0),
    "R": (1, 0, 0),
    "F": (0, 0, 1),
    "D": (0, -1, 0),
    "L": (-1, 0, 0),
    "B": (0, 0, -1),
}

MOVE_DESCRIPTIONS = {
    "U": "upper", "R": "right", "F": "front", "D": "down", "L": "left", "B": "back",
}


def _sticker_position(face: str, r: int, c: int) -> tuple[int, int, int]:
    """3D cubie position of the sticker at row r / column c of a face."""
    if face == "U":
        return (c - 1, 1, r - 1)
    if face == "R":
        return (1, 1 - r, 1 - c)
    if face == "F":
        return (c - 1, 1 - r, 1)
    if face == "D":
        return (c - 1, -1, 1 - r)
    if face == "L":
        return (-1, 1 - r, c - 1)
    if face == "B":
        return (1 - c, 1 - r, -1)
    raise ValueError(face)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _rotate_cw(v, n):
    """Rotate integer vector v by 90 degrees clockwise when looking at the n face.

    Rodrigues' formula with theta = -90 deg: v' = -(n x v) + n (n . v).
    """
    cx = _cross(n, v)
    d = _dot(n, v)
    return (-cx[0] + n[0] * d, -cx[1] + n[1] * d, -cx[2] + n[2] * d)


# (position, normal) -> facelet index
_STICKERS: list[tuple[tuple[int, int, int], tuple[int, int, int]]] = []
for _f in FACES:
    for _r in range(3):
        for _c in range(3):
            _STICKERS.append((_sticker_position(_f, _r, _c), _NORMALS[_f]))
_INDEX = {s: i for i, s in enumerate(_STICKERS)}


def _quarter_turn_perm(face: str) -> list[int]:
    """Gather-permutation p for a clockwise quarter turn: new[i] = old[p[i]]."""
    n = _NORMALS[face]
    perm = list(range(54))
    for i, (pos, nor) in enumerate(_STICKERS):
        if _dot(pos, n) == 1:  # sticker belongs to the turning layer
            j = _INDEX[(_rotate_cw(pos, n), _rotate_cw(nor, n))]
            perm[j] = i
    return perm


def _compose(p: list[int], q: list[int]) -> list[int]:
    """Permutation equivalent to applying p, then q."""
    return [p[q[i]] for i in range(54)]


PERMS: dict[str, list[int]] = {}
for _f in FACES:
    _q = _quarter_turn_perm(_f)
    _h = _compose(_q, _q)
    PERMS[_f] = _q
    PERMS[_f + "2"] = _h
    PERMS[_f + "'"] = _compose(_h, _q)


def inverse(move: str) -> str:
    if move.endswith("2"):
        return move
    if move.endswith("'"):
        return move[0]
    return move + "'"


def is_valid_move(move: str) -> bool:
    return move in PERMS


def apply_move(state: str, move: str) -> str:
    if move not in PERMS:
        raise ValueError(f"Invalid move: {move!r}")
    p = PERMS[move]
    return "".join([state[i] for i in p])


def apply_moves(state: str, moves: Iterable[str]) -> str:
    for m in moves:
        state = apply_move(state, m)
    return state


def parse_moves(text: str) -> list[str]:
    return [m for m in text.replace(",", " ").split() if m]


def is_solved(state: str) -> bool:
    """True when every one of the six faces shows a single colour."""
    return all(len(set(state[i * 9:(i + 1) * 9])) == 1 for i in range(6))


def faces(state: str) -> dict[str, list[list[str]]]:
    """Facelet string -> {face: 3x3 grid of colour letters}."""
    return {
        f: [list(state[k * 9 + r * 3: k * 9 + r * 3 + 3]) for r in range(3)]
        for k, f in enumerate(FACES)
    }


def describe_state(state: str) -> dict[str, str]:
    """Human/LLM-readable per-face rows, e.g. {"U": "UUF/UUF/UUF", ...}."""
    return {
        f: "/".join(state[k * 9 + r * 3: k * 9 + r * 3 + 3] for r in range(3))
        for k, f in enumerate(FACES)
    }


def solved_faces_count(state: str) -> int:
    return sum(len(set(state[i * 9:(i + 1) * 9])) == 1 for i in range(6))


def correct_stickers(state: str) -> int:
    """Stickers that match their face's centre colour (54 when solved)."""
    return sum(state[i] == state[(i // 9) * 9 + 4] for i in range(54))


def random_scramble(length: int, rng: random.Random) -> list[str]:
    """Random scramble with no two consecutive turns of the same face and no
    redundant opposite-face triples (e.g. R L R), so the length is meaningful."""
    opposite = {"U": "D", "D": "U", "R": "L", "L": "R", "F": "B", "B": "F"}
    seq: list[str] = []
    while len(seq) < length:
        m = rng.choice(MOVES)
        if seq and seq[-1][0] == m[0]:
            continue
        if len(seq) >= 2 and seq[-1][0] == opposite[m[0]] and seq[-2][0] == m[0]:
            continue
        seq.append(m)
    return seq


def move_criteria() -> dict[str, str]:
    """Shared option definitions for every model: move -> plain-English description."""
    out = {}
    for f in FACES:
        name = MOVE_DESCRIPTIONS[f]
        out[f] = f"Turn the {name} face clockwise by 90 degrees"
        out[f + "'"] = f"Turn the {name} face counterclockwise by 90 degrees"
        out[f + "2"] = f"Turn the {name} face by 180 degrees"
    return out
