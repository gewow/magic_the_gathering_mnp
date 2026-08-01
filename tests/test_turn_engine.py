"""
test_turn_engine.py — Member C's test suite

Assumed function signatures (update this file if your design differs
from these — the important part is agreeing on ONE version):

    turn_manager.get_next_phase(current_phase: str) -> str
        Given a phase from constants.PHASE_ORDER, returns the next one.
        Wraps back to "UNTAP" (with turn+1, active_player swapped) after "CLEANUP".

    priority.start_priority_window(state: dict) -> dict
        Sets state["priority_holder"] = state["active_player"], resets
        the internal pass-in-a-row counter. Returns the updated state.

    priority.handle_pass(state: dict, player_id: str) -> tuple[dict, str]
        Must reject if player_id != state["priority_holder"] (caller's job
        to have already checked NOT_YOUR_PRIORITY before calling this).
        Returns (updated_state, signal) where signal is one of:
            "CONTINUE"   — priority passed to the other player, window stays open
            "STEP_END"   — both passed consecutively, stack is empty
            "RESOLVE"    — both passed consecutively, stack has items to resolve

    priority.handle_stack_action(state: dict, stack_item: dict) -> dict
        Called when a player casts/activates something. Pushes stack_item
        onto state["stack"], resets the pass-in-a-row counter to 0, and
        keeps priority with the caster (does NOT flip priority_holder).

    sba.check_state_based_actions(state: dict) -> list[dict]
        Runs once. Returns a list of event dicts describing anything that
        happened, e.g. [{"type": "LIFE_ZERO", "loser": "player_2"}] or
        [{"type": "CREATURE_DIED", "card_id": "wall_of_stone_004"}].
        Returns [] if nothing triggers. Caller is responsible for calling
        this repeatedly until it returns [].

Run with: python3 tests/test_turn_engine.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                 "src", "magic_the_gethering_mnp"))

import constants  # noqa: E402

try:
    import turn_manager
    import priority
    import sba
except ImportError as exc:
    print(f"Cannot run tests yet — {exc}")
    print("Build turn_manager.py / priority.py / sba.py with the function "
          "signatures documented at the top of this file, then re-run.")
    sys.exit(1)

from mock_state import mock_precombat_main_state, mock_lethal_state  # noqa: E402


# ---------------------------------------------------------------------------
# Phase ordering
# ---------------------------------------------------------------------------

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
    assert next_phase == "UNTAP", \
        "After CLEANUP, the next turn's UNTAP must begin"
    print("PASS: test_cleanup_wraps_to_untap")


def test_untap_and_cleanup_are_not_priority_phases():
    assert "UNTAP" not in constants.PRIORITY_PHASES
    assert "CLEANUP" not in constants.PRIORITY_PHASES
    print("PASS: test_untap_and_cleanup_are_not_priority_phases")


# ---------------------------------------------------------------------------
# Priority pass loop
# ---------------------------------------------------------------------------

def test_priority_window_starts_with_active_player():
    state = mock_precombat_main_state()
    state = priority.start_priority_window(state)
    assert state["priority_holder"] == state["active_player"]
    print("PASS: test_priority_window_starts_with_active_player")


def test_both_pass_empty_stack_ends_step():
    state = mock_precombat_main_state()
    state["stack"] = []
    state = priority.start_priority_window(state)
    ap = state["active_player"]
    nap = "player_2" if ap == "player_1" else "player_1"

    state, signal_1 = priority.handle_pass(state, ap)
    assert signal_1 == "CONTINUE", "First pass should just hand priority over"
    state, signal_2 = priority.handle_pass(state, nap)
    assert signal_2 == "STEP_END", \
        "Both players passing consecutively with an empty stack must end the step"
    print("PASS: test_both_pass_empty_stack_ends_step")


def test_both_pass_nonempty_stack_resolves():
    state = mock_precombat_main_state()
    state = priority.start_priority_window(state)
    ap = state["active_player"]
    nap = "player_2" if ap == "player_1" else "player_1"

    state = priority.handle_stack_action(state, {
        "stack_item_id": "stk_test", "item_type": "SPELL",
        "source": "lightning_bolt_001", "targets": [nap], "controller": ap,
    })
    assert len(state["stack"]) == 1

    state, signal_1 = priority.handle_pass(state, ap)
    state, signal_2 = priority.handle_pass(state, nap)
    assert signal_2 == "RESOLVE", \
        "Both passing with a non-empty stack must signal RESOLVE, not STEP_END"
    print("PASS: test_both_pass_nonempty_stack_resolves")


def test_casting_resets_the_pass_counter():
    """
    This is the #1 real-world bug in priority implementations: casting
    something must reset the "both passed in a row" counter, even if
    one pass already happened before the cast.
    """
    state = mock_precombat_main_state()
    state = priority.start_priority_window(state)
    ap = state["active_player"]
    nap = "player_2" if ap == "player_1" else "player_1"

    state, _ = priority.handle_pass(state, ap)          # AP passes once
    state = priority.handle_stack_action(state, {        # NAP casts something
        "stack_item_id": "stk_test2", "item_type": "SPELL",
        "source": "shock_001", "targets": [ap], "controller": nap,
    })
    # Now it must take TWO fresh consecutive passes to resolve — the
    # earlier AP pass must not count toward this new window.
    state, signal_1 = priority.handle_pass(state, nap)
    assert signal_1 == "CONTINUE", \
        "A single pass right after a new cast must not immediately resolve"
    print("PASS: test_casting_resets_the_pass_counter")


def test_priority_returns_to_active_player_after_resolution():
    """
    RFC Section 8.1 rule 5: after a stack item resolves, the ACTIVE
    PLAYER receives priority again — not whoever passed last.
    """
    state = mock_precombat_main_state()
    state = priority.start_priority_window(state)
    ap = state["active_player"]
    nap = "player_2" if ap == "player_1" else "player_1"
    state = priority.handle_stack_action(state, {
        "stack_item_id": "stk_test3", "item_type": "SPELL",
        "source": "lightning_bolt_002", "targets": [nap], "controller": ap,
    })
    state, _ = priority.handle_pass(state, ap)
    state, signal = priority.handle_pass(state, nap)
    assert signal == "RESOLVE"
    # After the caller pops/resolves the stack item and calls
    # start_priority_window again, it must go back to AP:
    state = priority.start_priority_window(state)
    assert state["priority_holder"] == ap
    print("PASS: test_priority_returns_to_active_player_after_resolution")


# ---------------------------------------------------------------------------
# State-based actions
# ---------------------------------------------------------------------------

def test_sba_detects_life_zero():
    state = mock_lethal_state()
    state["life_totals"]["player_2"] = 0  # simulate Lightning Bolt having resolved
    events = sba.check_state_based_actions(state)
    life_zero_events = [e for e in events if e["type"] == "LIFE_ZERO"]
    assert len(life_zero_events) == 1
    assert life_zero_events[0]["loser"] == "player_2"
    print("PASS: test_sba_detects_life_zero")


def test_sba_detects_lethal_creature_damage():
    state = mock_lethal_state()
    # Give Player 2's wall lethal damage
    state["battlefield"]["player_2"] = [
        {"id": "wall_of_stone_004", "tapped": False, "damage": 8,
         "power": 0, "toughness": 8, "summoning_sick": False}
    ]
    events = sba.check_state_based_actions(state)
    died = [e for e in events if e["type"] == "CREATURE_DIED"]
    assert any(e["card_id"] == "wall_of_stone_004" for e in died), \
        "A creature with damage >= toughness must be detected as dying"
    print("PASS: test_sba_detects_lethal_creature_damage")


def test_sba_returns_empty_when_nothing_triggers():
    state = mock_precombat_main_state()
    events = sba.check_state_based_actions(state)
    assert events == [], "A perfectly normal state should trigger no SBAs"
    print("PASS: test_sba_returns_empty_when_nothing_triggers")


if __name__ == "__main__":
    test_phase_order_matches_constants()
    test_cleanup_wraps_to_untap()
    test_untap_and_cleanup_are_not_priority_phases()
    test_priority_window_starts_with_active_player()
    test_both_pass_empty_stack_ends_step()
    test_both_pass_nonempty_stack_resolves()
    test_casting_resets_the_pass_counter()
    test_priority_returns_to_active_player_after_resolution()
    test_sba_detects_life_zero()
    test_sba_detects_lethal_creature_damage()
    test_sba_returns_empty_when_nothing_triggers()
    print("\nAll turn engine / priority / SBA tests passed.")
