"""
test_stage3_bugfixes.py

Regression tests for 4 issues found reviewing the original Stage 3
submission. Each test reproduces the exact scenario that exposed the
bug, so if any of these ever start failing again, you'll know
immediately which specific issue regressed.

Run with: python3 tests/test_stage3_bugfixes.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                 "src", "magic_the_gethering_mnp"))
sys.path.insert(0, os.path.dirname(__file__))

import sba  # noqa: E402
import priority  # noqa: E402
from mock_state import mock_combat_state_with_blockers, mock_lethal_state, \
    mock_precombat_main_state  # noqa: E402


# ---------------------------------------------------------------------------
# Bug 1: sba.py must detect lethal damage on REAL schema-conformant
# creatures (no "type" key, field is "damage" not "damage_marked")
# ---------------------------------------------------------------------------

def test_sba_detects_lethal_damage_on_real_schema_creature():
    state = mock_combat_state_with_blockers()
    wall = next(p for p in state["battlefield"]["player_2"]
                if p["id"] == "wall_of_stone_004")
    wall["damage"] = 8  # exactly lethal -- toughness is 8

    events = sba.check_state_based_actions(state)
    died = [e for e in events if e["type"] == "CREATURE_DIED"]
    assert len(died) == 1, \
        f"Expected wall_of_stone_004 to be detected as dead, got: {events}"
    assert died[0]["card_id"] == "wall_of_stone_004"
    print("PASS: test_sba_detects_lethal_damage_on_real_schema_creature")


def test_sba_ignores_non_creature_permanents():
    """A land (no 'toughness' key) must never be treated as a creature."""
    state = mock_precombat_main_state()
    events = sba.check_state_based_actions(state)
    # mountain_003 has no toughness -- must not appear as CREATURE_DIED
    # under any circumstance, since it can't take damage in the first place.
    assert all(e.get("card_id") != "mountain_003" for e in events)
    print("PASS: test_sba_ignores_non_creature_permanents")


# ---------------------------------------------------------------------------
# Bug 2: simultaneous life-zero must produce exactly ONE event, with the
# Active Player as the loser (RFC 8.4)
# ---------------------------------------------------------------------------

def test_simultaneous_life_zero_produces_one_event_ap_loses():
    state = mock_lethal_state()
    state["active_player"] = "player_1"
    state["life_totals"]["player_1"] = 0
    state["life_totals"]["player_2"] = 0

    events = sba.check_state_based_actions(state)
    life_zero_events = [e for e in events if e["type"] == "LIFE_ZERO"]
    assert len(life_zero_events) == 1, \
        f"Expected exactly ONE LIFE_ZERO event on simultaneous KO, got {len(life_zero_events)}"
    assert life_zero_events[0]["loser"] == "player_1", \
        "RFC 8.4: on simultaneous life-zero, the ACTIVE PLAYER loses"
    assert life_zero_events[0]["winner"] == "player_2"
    print("PASS: test_simultaneous_life_zero_produces_one_event_ap_loses")


def test_single_player_life_zero_still_works_normally():
    state = mock_lethal_state()
    state["life_totals"]["player_2"] = 0
    events = sba.check_state_based_actions(state)
    life_zero_events = [e for e in events if e["type"] == "LIFE_ZERO"]
    assert len(life_zero_events) == 1
    assert life_zero_events[0]["loser"] == "player_2"
    print("PASS: test_single_player_life_zero_still_works_normally")


# ---------------------------------------------------------------------------
# Bug 3: a multi-target spell fizzles only if ALL targets are illegal,
# not if just one of several is illegal
# ---------------------------------------------------------------------------

def test_partial_illegal_targets_still_resolves():
    state = mock_precombat_main_state()
    state["stack"] = [{
        "stack_item_id": "stk_multi",
        "targets": ["player_2", "nonexistent_creature_999"],
    }]
    state, event = priority.resolve_top_of_stack(state)
    assert event["result"] == "RESOLVED", \
        "A spell with at least one legal target must resolve, not fizzle"
    print("PASS: test_partial_illegal_targets_still_resolves")


def test_all_illegal_targets_still_fizzles():
    state = mock_precombat_main_state()
    state["stack"] = [{
        "stack_item_id": "stk_all_bad",
        "targets": ["nonexistent_creature_999", "also_fake_888"],
    }]
    state, event = priority.resolve_top_of_stack(state)
    assert event["result"] == "FIZZLE", \
        "A spell with NO legal targets remaining must still fizzle"
    print("PASS: test_all_illegal_targets_still_fizzles")


# ---------------------------------------------------------------------------
# Bug 4: a spell targeting another item still on the stack (Counterspell)
# must be recognized as a legal target
# ---------------------------------------------------------------------------

def test_counterspell_style_stack_target_is_legal():
    state = mock_precombat_main_state()
    state["stack"] = [
        {"stack_item_id": "stk_bolt", "targets": ["player_2"]},
        {"stack_item_id": "stk_counter", "targets": ["stk_bolt"]},
    ]
    state, event = priority.resolve_top_of_stack(state)
    assert event["result"] == "RESOLVED", \
        "Targeting another spell still on the stack must be legal"
    assert event["stack_item_id"] == "stk_counter"
    # The targeted spell should still be sitting on the stack, untouched --
    # resolving the Counterspell itself doesn't remove its target; the
    # actual "counter that spell" effect is Member D's card-effect logic,
    # applied via apply_effect_fn, not this generic stack mechanic.
    assert len(state["stack"]) == 1
    assert state["stack"][0]["stack_item_id"] == "stk_bolt"
    print("PASS: test_counterspell_style_stack_target_is_legal")


if __name__ == "__main__":
    test_sba_detects_lethal_damage_on_real_schema_creature()
    test_sba_ignores_non_creature_permanents()
    test_simultaneous_life_zero_produces_one_event_ap_loses()
    test_single_player_life_zero_still_works_normally()
    test_partial_illegal_targets_still_resolves()
    test_all_illegal_targets_still_fizzles()
    test_counterspell_style_stack_target_is_legal()
    print("\nAll Stage 3 bugfix regression tests passed.")
