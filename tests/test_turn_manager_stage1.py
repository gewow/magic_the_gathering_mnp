"""
test_turn_manager_stage1.py

Tests ONLY what Stage 1 built: get_next_phase() and advance_phase()'s
turn/active_player handoff logic. Deliberately does NOT import
priority.py or sba.py, since those don't exist yet at this stage —
this lets you verify Stage 1 in isolation before building Stage 2.

Run with: python3 tests/test_turn_manager_stage1.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                 "src", "magic_the_gethering_mnp"))

import constants  # noqa: E402
import turn_manager  # noqa: E402


def test_phase_order_matches_constants():
    for i in range(len(constants.PHASE_ORDER) - 1):
        current = constants.PHASE_ORDER[i]
        expected_next = constants.PHASE_ORDER[i + 1]
        actual_next = turn_manager.get_next_phase(current)
        assert actual_next == expected_next, \
            f"After {current}, expected {expected_next}, got {actual_next}"
    print("PASS: test_phase_order_matches_constants")


def test_cleanup_wraps_to_untap():
    next_phase = turn_manager.get_next_phase("CLEANUP")
    assert next_phase == "UNTAP"
    print("PASS: test_cleanup_wraps_to_untap")


def test_unknown_phase_raises():
    try:
        turn_manager.get_next_phase("NOT_A_REAL_PHASE")
        raised = False
    except ValueError:
        raised = True
    assert raised, "An unknown phase name should raise ValueError"
    print("PASS: test_unknown_phase_raises")


def test_advance_phase_normal_step_no_turn_change():
    state = {"phase": "UPKEEP", "turn": 3, "active_player": "player_1"}
    state = turn_manager.advance_phase(state)
    assert state["phase"] == "DRAW"
    assert state["turn"] == 3, "Turn number must not change on a normal phase advance"
    assert state["active_player"] == "player_1", \
        "Active player must not change on a normal phase advance"
    print("PASS: test_advance_phase_normal_step_no_turn_change")


def test_advance_phase_cleanup_to_untap_increments_turn():
    state = {"phase": "CLEANUP", "turn": 3, "active_player": "player_1"}
    state = turn_manager.advance_phase(state)
    assert state["phase"] == "UNTAP"
    assert state["turn"] == 4, "Turn number must increment on CLEANUP -> UNTAP"
    print("PASS: test_advance_phase_cleanup_to_untap_increments_turn")


def test_advance_phase_cleanup_to_untap_swaps_active_player():
    state = {"phase": "CLEANUP", "turn": 3, "active_player": "player_1"}
    state = turn_manager.advance_phase(state)
    assert state["active_player"] == "player_2", \
        "Active player must swap on CLEANUP -> UNTAP"

    state2 = {"phase": "CLEANUP", "turn": 4, "active_player": "player_2"}
    state2 = turn_manager.advance_phase(state2)
    assert state2["active_player"] == "player_1", \
        "Active player must swap back the other way too"
    print("PASS: test_advance_phase_cleanup_to_untap_swaps_active_player")


def test_full_turn_cycle_returns_to_untap_with_correct_handoff():
    """
    Walks a state through every phase of a full turn, one advance_phase()
    call at a time, and confirms it ends up back at UNTAP with turn+1
    and the active player swapped -- proving the whole 14-step loop is
    wired correctly, not just the two endpoints.
    """
    state = {"phase": "UNTAP", "turn": 1, "active_player": "player_1"}
    for _ in range(len(constants.PHASE_ORDER)):
        state = turn_manager.advance_phase(state)
    assert state["phase"] == "UNTAP"
    assert state["turn"] == 2
    assert state["active_player"] == "player_2"
    print("PASS: test_full_turn_cycle_returns_to_untap_with_correct_handoff")


if __name__ == "__main__":
    test_phase_order_matches_constants()
    test_cleanup_wraps_to_untap()
    test_unknown_phase_raises()
    test_advance_phase_normal_step_no_turn_change()
    test_advance_phase_cleanup_to_untap_increments_turn()
    test_advance_phase_cleanup_to_untap_swaps_active_player()
    test_full_turn_cycle_returns_to_untap_with_correct_handoff()
    print("\nAll Stage 1 turn_manager.py tests passed.")
