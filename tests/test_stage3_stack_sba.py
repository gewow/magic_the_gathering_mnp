"""
Stage 3 tests -- Stack Resolution + SBAs (sba.py / priority.py)

Drop this file into your tests/ folder (next to test_turn_engine.py and
mock_state.py) and run:

    python3 tests/test_stage3_stack_sba.py

It assumes:
  - sba.py exposes: check_state_based_actions, apply_sba_events, run_sba_until_stable
  - priority.py exposes: resolve_top_of_stack, process_stack_and_sbas
  - tests/mock_state.py exposes: mock_precombat_main_state(), mock_lethal_state()

If any import fails, fix the path/name first -- these tests assume the
Stage 3 code from the design doc is in place.
"""

import sys
import os
import traceback

# Make sure "tests/" (this file's own directory) is importable so
# `import mock_state` works regardless of where you invoke this from.
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(THIS_DIR)
sys.path.insert(0, THIS_DIR)
# Also add the project root (one level up) so `import sba` / `import priority`
# resolve if those files live at the project root rather than in tests/.
sys.path.insert(0, PROJECT_ROOT)
# Your sba.py / priority.py currently live under src/magic_the_gethering_mnp/
# -- add that specific folder too. (If you ever rename the folder to fix the
# "gethering" typo, this line still works since it's built from PROJECT_ROOT.)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src", "magic_the_gethering_mnp"))

import sba
import priority
from mock_state import mock_precombat_main_state, mock_lethal_state


# ---------------------------------------------------------------------------
# sba.py tests
# ---------------------------------------------------------------------------

def test_sba_detects_life_zero():
    # mock_lethal_state() is the PRE-lethal state (player_2 at 3, matching
    # RFC Step 31 right before the Bolt resolves) -- not already dead. Force
    # the zero-life condition directly to test the SBA check in isolation.
    state = mock_lethal_state()
    state["life_totals"]["player_2"] = 0
    events = sba.check_state_based_actions(state)
    life_zero_events = [e for e in events if e["type"] == "LIFE_ZERO"]
    assert len(life_zero_events) == 1, "expected exactly one LIFE_ZERO event"
    assert life_zero_events[0]["loser"] in state["life_totals"]


def test_sba_detects_lethal_creature_damage():
    state = mock_precombat_main_state()
    state["battlefield"]["player_1"].append({
        "id": "test_creature_001", "tapped": False,
        "power": 1, "toughness": 2, "damage": 2, "summoning_sick": False,
    })
    events = sba.check_state_based_actions(state)
    died_events = [e for e in events if e["type"] == "CREATURE_DIED"]
    assert len(died_events) == 1, "expected exactly one CREATURE_DIED event"
    assert died_events[0]["card_id"] == "test_creature_001"


def test_sba_returns_empty_when_nothing_triggers():
    state = mock_precombat_main_state()
    events = sba.check_state_based_actions(state)
    assert events == [], f"expected no events, got {events}"


def test_run_sba_until_stable_moves_dead_creature_to_graveyard():
    state = mock_precombat_main_state()
    state["battlefield"]["player_1"].append({
        "id": "test_creature_001", "tapped": False,
        "power": 1, "toughness": 2, "damage": 3, "summoning_sick": False,
    })
    state, events, game_over = sba.run_sba_until_stable(state)
    assert game_over is None, "should not be game over from a creature dying"
    assert all(p["id"] != "test_creature_001" for p in state["battlefield"]["player_1"]), \
        "dead creature should be removed from battlefield"
    assert "test_creature_001" in state["graveyard"]["player_1"], \
        "dead creature should be in graveyard"


def test_run_sba_until_stable_stops_on_life_zero():
    state = mock_lethal_state()
    state["life_totals"]["player_2"] = 0
    state, events, game_over = sba.run_sba_until_stable(state)
    assert game_over is not None, "expected a game_over event"
    assert game_over["type"] == "LIFE_ZERO"


# ---------------------------------------------------------------------------
# priority.py tests
# ---------------------------------------------------------------------------

def test_resolve_top_of_stack_pops_lifo():
    state = mock_precombat_main_state()
    state["stack"] = [
        {"stack_item_id": "stk_01", "targets": []},
        {"stack_item_id": "stk_02", "targets": []},
    ]
    state, event = priority.resolve_top_of_stack(state)
    assert event["stack_item_id"] == "stk_02", "should resolve last-pushed item first (LIFO)"
    assert len(state["stack"]) == 1


def test_resolve_top_of_stack_fizzles_on_illegal_target():
    state = mock_precombat_main_state()
    state["stack"] = [{
        "stack_item_id": "stk_01",
        "targets": ["nonexistent_creature_999"],
    }]
    state, event = priority.resolve_top_of_stack(state)
    assert event["result"] == "FIZZLE"


def test_resolve_top_of_stack_calls_apply_effect_fn_on_legal_resolve():
    state = mock_precombat_main_state()
    state["stack"] = [{
        "stack_item_id": "stk_01",
        "targets": ["player_2"],
    }]

    def fake_bolt(state, stack_item):
        state["life_totals"]["player_2"] -= 3
        return state, [{"type": "DAMAGE", "target": "player_2", "amount": 3}]

    state, event = priority.resolve_top_of_stack(state, apply_effect_fn=fake_bolt)
    assert event["result"] == "RESOLVED"
    assert event["state_changes"][0]["amount"] == 3
    assert state["life_totals"]["player_2"] == 17


def test_process_stack_and_sbas_returns_priority_to_active_player():
    state = mock_precombat_main_state()
    state["stack"] = [{"stack_item_id": "stk_01", "targets": []}]
    result = priority.process_stack_and_sbas(state)
    assert result["game_over"] is None
    assert result["next_priority_to"] == result["state"]["active_player"]


def test_process_stack_and_sbas_reports_game_over_no_priority_key():
    # mock_lethal_state() has player_2 at 3 life -- mirrors the RFC's own
    # Step 31 scenario (Lightning Bolt for 3 dealing exactly lethal). Use a
    # fake effect fn that applies that 3 damage, same as the real
    # lightning_bolt effect would, rather than assuming life is pre-zeroed.
    state = mock_lethal_state()
    state["stack"] = [{"stack_item_id": "stk_01", "targets": ["player_2"]}]

    def fake_lethal_bolt(state, stack_item):
        state["life_totals"]["player_2"] -= 3
        return state, [{"type": "DAMAGE", "target": "player_2", "amount": 3}]

    result = priority.process_stack_and_sbas(state, apply_effect_fn=fake_lethal_bolt)
    assert result["game_over"] is not None
    assert "next_priority_to" not in result


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

ALL_TESTS = [
    test_sba_detects_life_zero,
    test_sba_detects_lethal_creature_damage,
    test_sba_returns_empty_when_nothing_triggers,
    test_run_sba_until_stable_moves_dead_creature_to_graveyard,
    test_run_sba_until_stable_stops_on_life_zero,
    test_resolve_top_of_stack_pops_lifo,
    test_resolve_top_of_stack_fizzles_on_illegal_target,
    test_resolve_top_of_stack_calls_apply_effect_fn_on_legal_resolve,
    test_process_stack_and_sbas_returns_priority_to_active_player,
    test_process_stack_and_sbas_reports_game_over_no_priority_key,
]


def run_all():
    passed = 0
    failed = 0
    for test_fn in ALL_TESTS:
        name = test_fn.__name__
        try:
            test_fn()
            print(f"PASS: {name}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL: {name} -- {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR: {name} -- {type(e).__name__}: {e}")
            traceback.print_exc()
            failed += 1

    print()
    print(f"{passed}/{len(ALL_TESTS)} passed, {failed} failed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    run_all()