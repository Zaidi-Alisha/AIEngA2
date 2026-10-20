import random

from app.cube import (
    MOVES, SOLVED, apply_move, apply_moves, inverse, is_solved, parse_moves, random_scramble,
)
from app.solver import MAX_EXACT, best_next_moves, optimal_distance, optimal_solution


def test_single_r_matches_kociemba_reference():
    # Reference facelet string for the move R applied to a solved cube (kociemba order).
    expected = (
        "UUFUUFUUF" "RRRRRRRRR" "FFDFFDFFD" "DDBDDBDDB" "LLLLLLLLL" "UBBUBBUBB"
    )
    assert apply_move(SOLVED, "R") == expected


def test_single_u_moves_front_row_to_left():
    s = apply_move(SOLVED, "U")
    assert s[36:39] == "FFF"  # L top row now shows the old F colour
    assert s[18:21] == "RRR"  # F top row now shows the old R colour


def test_every_move_has_order_and_inverse():
    for m in MOVES:
        assert apply_moves(SOLVED, [m, inverse(m)]) == SOLVED
        k = 2 if m.endswith("2") else 4
        assert apply_moves(SOLVED, [m] * k) == SOLVED
        assert not is_solved(apply_move(SOLVED, m))


def test_known_group_orders():
    sexy = parse_moves("R U R' U'")
    s = SOLVED
    for i in range(1, 7):
        s = apply_moves(s, sexy)
        assert (s == SOLVED) == (i == 6)
    s, n = apply_moves(SOLVED, ["R", "U"]), 1
    while s != SOLVED:
        s, n = apply_moves(s, ["R", "U"]), n + 1
    assert n == 105


def test_solver_is_exact_and_valid():
    rng = random.Random(7)
    for length in range(0, 7):
        for _ in range(15):
            scr = random_scramble(length, rng)
            st = apply_moves(SOLVED, scr)
            sol = optimal_solution(st)
            assert sol is not None
            assert len(sol) <= length
            assert apply_moves(st, sol) == SOLVED


def test_solver_known_distances():
    assert optimal_distance(SOLVED) == 0
    assert optimal_distance(apply_moves(SOLVED, parse_moves("R U"))) == 2
    assert optimal_distance(apply_moves(SOLVED, parse_moves("R L"))) == 2
    assert optimal_distance(apply_moves(SOLVED, parse_moves("R U R' U'"))) == 4
    # Sune-like 7 mover is within the exact range.
    st = apply_moves(SOLVED, parse_moves("R U R' U R U2 R'"))
    assert optimal_distance(st) == 7 <= MAX_EXACT


def test_best_next_moves_reduce_distance():
    st = apply_moves(SOLVED, parse_moves("F R2 U'"))
    d = optimal_distance(st)
    for m in best_next_moves(st):
        assert optimal_distance(apply_move(st, m)) == d - 1
