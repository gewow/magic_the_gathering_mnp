"""
test_pdu_and_state.py

Confirms:
  1. pdu.py builders produce valid, correctly-shaped PDUs.
  2. game_state.personalize_state() actually hides the opponent's hand
     (this is the single most important correctness property in the
     whole protocol — get it wrong and you leak hidden information).

Run with: python3 tests/test_pdu_and_state.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                 "src", "magic_the_gethering_mnp"))

import pdu  # noqa: E402
import game_state  # noqa: E402
from mock_state import mock_precombat_main_state  # noqa: E402


def test_builders_produce_valid_basic_shape():
    samples = [
        pdu.build_player_ready(1, "player_1", ["mountain_001"]),
        pdu.build_priority_pass(5),
        pdu.build_cast_spell(7, "lightning_bolt_001", ["player_2"], {"R": 1}),
        pdu.build_priority_grant(8, "player_1"),
        pdu.build_stack_push(8, "stk_01", "SPELL", "lightning_bolt_001",
                              ["player_2"], "player_1"),
        pdu.build_game_over(100, "player_1", "player_2",
                             __import__("constants").REASON_LIFE_ZERO),
        pdu.build_error(14, __import__("constants").ERROR_STALE_ACTION,
                        "bad seq_num"),
        pdu.build_ping(1, 1745000000000),
        pdu.build_pong(1, 1745000000000),
    ]
    for p in samples:
        ok, reason = pdu.validate_basic(p)
        assert ok, f"Builder produced invalid PDU: {p} ({reason})"
    print("PASS: test_builders_produce_valid_basic_shape")


def test_unknown_type_rejected():
    bad = {"type": "NOT_A_REAL_TYPE", "seq_num": 1}
    ok, reason = pdu.validate_basic(bad)
    assert not ok, "Expected validate_basic to reject an unknown type"
    print("PASS: test_unknown_type_rejected")


def test_priority_echo_classification():
    assert pdu.requires_priority_echo("CAST_SPELL") is True
    assert pdu.requires_priority_echo("PRIORITY_PASS") is True
    assert pdu.requires_priority_echo("CONCEDE") is False
    assert pdu.requires_priority_echo("PING") is False
    print("PASS: test_priority_echo_classification")


def test_personalize_hides_opponent_hand():
    state = mock_precombat_main_state()

    visible_p1 = game_state.personalize_state(state, "player_1")
    visible_p2 = game_state.personalize_state(state, "player_2")

    # Player 1 should see their own full hand...
    assert visible_p1["hand"] == state["hands"]["player_1"]
    # ...and only a COUNT for player 2, never the actual cards.
    assert "hand" not in visible_p1 or visible_p1.get("hand") != state["hands"]["player_2"]
    assert visible_p1["hand_counts"]["player_2"] == len(state["hands"]["player_2"])

    # Symmetric check for player 2's view.
    assert visible_p2["hand"] == state["hands"]["player_2"]
    assert visible_p2["hand_counts"]["player_1"] == len(state["hands"]["player_1"])

    # Neither player's view should ever contain the raw library order.
    assert "libraries" not in visible_p1
    assert "libraries" not in visible_p2
    assert visible_p1["library_counts"]["player_1"] == len(state["libraries"]["player_1"])

    print("PASS: test_personalize_hides_opponent_hand")


def test_seq_num_counter_increments():
    state = game_state.create_initial_state()
    first = game_state.next_seq_num(state)
    second = game_state.next_seq_num(state)
    assert second == first + 1, "Server seq_num counter must strictly increase"
    print("PASS: test_seq_num_counter_increments")


if __name__ == "__main__":
    test_builders_produce_valid_basic_shape()
    test_unknown_type_rejected()
    test_priority_echo_classification()
    test_personalize_hides_opponent_hand()
    test_seq_num_counter_increments()
    print("\nAll pdu.py / game_state.py tests passed.")
