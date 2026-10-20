"""Exact shortest-path solver (half-turn metric) for shallow cube states.

Meet-in-the-middle breadth-first search:
  * A backward BFS from the solved cube is built once, to depth BACK_DEPTH. For every
    state it stores the distance to solved and one move that goes one step closer.
  * A forward BFS from the query state (depth <= FRONT_DEPTH) stops at the first layer
    that touches the backward table.

Because both halves are complete BFS layers, the first meeting depth is the exact
optimum. With 4 + 4 the solver is exact for any state up to 8 moves from solved, which
covers the warm-up (3-4) and primary (4-5) benchmark sets with room to spare.
"""

from __future__ import annotations

import threading
from functools import lru_cache

from .cube import MOVES, PERMS, SOLVED, inverse

BACK_DEPTH = 4
FRONT_DEPTH = 4
MAX_EXACT = BACK_DEPTH + FRONT_DEPTH

_OPPOSITE = {"U": "D", "D": "U", "R": "L", "L": "R", "F": "B", "B": "F"}
_ORDER = {f: i for i, f in enumerate("URFDLB")}


def _allowed(prev: str | None, m: str) -> bool:
    """Prune sequences that can never be shortest: same face twice, or opposite
    faces in non-canonical order (they commute, so only one order is needed)."""
    if prev is None:
        return True
    if prev[0] == m[0]:
        return False
    if _OPPOSITE[prev[0]] == m[0] and _ORDER[prev[0]] > _ORDER[m[0]]:
        return False
    return True


def _apply(state: str, m: str) -> str:
    p = PERMS[m]
    return "".join([state[i] for i in p])


_table_lock = threading.Lock()
_table: dict[str, tuple[int, str | None]] | None = None


def _backward_table() -> dict[str, tuple[int, str | None]]:
    """state -> (distance to solved, a move that reduces the distance by one)."""
    global _table
    with _table_lock:
        if _table is not None:
            return _table
        table: dict[str, tuple[int, str | None]] = {SOLVED: (0, None)}
        frontier: list[tuple[str, str | None]] = [(SOLVED, None)]
        for depth in range(1, BACK_DEPTH + 1):
            nxt: list[tuple[str, str | None]] = []
            for s, last in frontier:
                for m in MOVES:
                    if not _allowed(last, m):
                        continue
                    t = _apply(s, m)
                    if t not in table:
                        # From t, undoing m goes back to s, which is one step closer.
                        table[t] = (depth, inverse(m))
                        nxt.append((t, m))
            frontier = nxt
        _table = table
        return table


def warm_up() -> int:
    return len(_backward_table())


def _follow_table(state: str, table) -> list[str]:
    path: list[str] = []
    while state != SOLVED:
        _, m = table[state]
        path.append(m)
        state = _apply(state, m)
    return path


@lru_cache(maxsize=20000)
def optimal_solution(state: str, limit: int = MAX_EXACT) -> tuple[str, ...] | None:
    """Exact shortest solution, or None if the state is more than `limit` moves away
    (limit is capped at MAX_EXACT)."""
    table = _backward_table()
    if state in table:
        return tuple(_follow_table(state, table)) if table[state][0] <= limit else None
    # Forward BFS, layer by layer. Within one layer, the best meeting point is the
    # one whose backward distance is smallest.
    frontier: list[tuple[str, str | None, tuple[str, ...]]] = [(state, None, ())]
    seen = {state}
    for depth in range(1, min(FRONT_DEPTH, limit - BACK_DEPTH) + 1):
        nxt = []
        best = None
        for s, last, path in frontier:
            for m in MOVES:
                if not _allowed(last, m):
                    continue
                t = _apply(s, m)
                if t in seen:
                    continue
                seen.add(t)
                p2 = path + (m,)
                hit = table.get(t)
                if hit is not None and (best is None or hit[0] < best[0]):
                    best = (hit[0], t, p2)
                nxt.append((t, m, p2))
        if best is not None:
            # Any state at forward depth d with backward distance k gives d + k.
            # Layers are complete, so the minimum over this layer is optimal only if no
            # shallower combination exists, which BFS order guarantees for d + BACK_DEPTH.
            return best[2] + tuple(_follow_table(best[1], table))
        frontier = nxt
    return None


def optimal_distance(state: str, limit: int = MAX_EXACT) -> int | None:
    sol = optimal_solution(state, limit)
    return None if sol is None else len(sol)


def best_next_moves(state: str, limit: int = MAX_EXACT) -> list[str]:
    """All moves that start some shortest solution (empty if solved or farther than limit)."""
    d = optimal_distance(state, limit)
    if not d:
        return []
    out = []
    for m in MOVES:
        nd = optimal_distance(_apply(state, m), d - 1)
        if nd is not None and nd == d - 1:
            out.append(m)
    return out
