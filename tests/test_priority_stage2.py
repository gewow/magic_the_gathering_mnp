"""
test_priority_stage2.py

Tests ONLY what Stage 2 built: start_priority_window(), handle_pass(),
and handle_stack_action(). Deliberately does NOT test actual stack
resolution (popping/applying effects) or SBAs — that's Stage 3.

Run with: python3 tests/test_priority_stage2.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                 "src", "magic_the_gethering_mnp"))

import priority  # noqa: E402


def _fresh_state(active_player="player_1", stack=None):
    return {
        "active_player": active_player,
        "priority_holder": None,
        "stack": stack if stack is not None else [],
    }


# ---------------------------------------------------------------------------
# start_priority_window
# ---------------------------------------------------------------------------

def test_window_starts_with_active_player():
    state = _fresh_state(active_player="player_2")
    state = priority.start_priority_window(state)
    assert state["priority_holder"] == "player_2"
    assert state["_pass_count"] == 0
    print("PASS: test_window_starts_with_active_player")


# ---------------------------------------------------------------------------
# handle_pass — basic flow
# ---------------------------------------------------------------------------

def test_first_pass_flips_priority_and_continues():
    state = _fresh_state()
    state = priority.start_priority_window(state)
    state, signal = priority.handle_pass(state, "player_1")
    assert signal == "CONTINUE"
    assert state["priority_holder"] == "player_2", \
        "Priority must flip to the other player after a pass (RFC 8.1 rule 4)"
    print("PASS: test_first_pass_flips_priority_and_continues")


def test_both_pass_empty_stack_ends_step():
    state = _fresh_state()
    state = priority.start_priority_window(state)
    state, signal_1 = priority.handle_pass(state, "player_1")
    assert signal_1 == "CONTINUE"
    state, signal_2 = priority.handle_pass(state, "player_2")
    assert signal_2 == "STEP_END", \
        "Two consecutive passes with an empty stack must end the step"
    print("PASS: test_both_pass_empty_stack_ends_step")


def test_both_pass_nonempty_stack_signals_resolve():
    fake_item = {"stack_item_id": "stk_test", "item_type": "SPELL",
                 "source": "lightning_bolt_001", "targets": ["player_2"],
                 "controller": "player_1"}
    state = _fresh_state(stack=[fake_item])
    state = priority.start_priority_window(state)
    state, _ = priority.handle_pass(state, "player_1")
    state, signal = priority.handle_pass(state, "player_2")
    assert signal == "RESOLVE", \
        "Two consecutive passes with a non-empty stack must signal RESOLVE"
    print("PASS: test_both_pass_nonempty_stack_signals_resolve")


def test_passing_out_of_turn_raises():
    state = _fresh_state()
    state = priority.start_priority_window(state)  # player_1 holds priority
    try:
        priority.handle_pass(state, "player_2")  # wrong player tries to pass
        raised = False
    except ValueError:
        raised = True
    assert raised, \
        "A player who does not hold priority attempting to pass must raise"
    print("PASS: test_passing_out_of_turn_raises")


# ---------------------------------------------------------------------------
# handle_stack_action
# ---------------------------------------------------------------------------

def test_casting_pushes_stack_and_keeps_priority_with_caster():
    state = _fresh_state()
    state = priority.start_priority_window(state)  # player_1 holds priority
    stack_item = {"stack_item_id": "stk_01", "item_type": "SPELL",
                  "source": "goblin_guide_001", "targets": [],
                  "controller": "player_1"}
    state = priority.handle_stack_action(state, stack_item)
    assert len(state["stack"]) == 1
    assert state["priority_holder"] == "player_1", \
        "The caster must RETAIN priority after casting (RFC 8.1 rule 3)"
    print("PASS: test_casting_pushes_stack_and_keeps_priority_with_caster")


def test_casting_resets_the_pass_counter():
    """
    The single most common priority bug: a cast must reset the pass
    counter, even if one pass already happened before it.
    """
    state = _fresh_state()
    state = priority.start_priority_window(state)
    state, _ = priority.handle_pass(state, "player_1")  # 1 pass so far
    assert state["_pass_count"] == 1

    stack_item = {"stack_item_id": "stk_02", "item_type": "SPELL",
                  "source": "shock_001", "targets": ["player_1"],
                  "controller": "player_2"}
    state = priority.handle_stack_action(state, stack_item)
    assert state["_pass_count"] == 0, \
        "Casting must reset the pass counter to 0, not leave it at 1"

    # Now it should take TWO FRESH passes to reach STEP_END/RESOLVE,
    # not just one more (which would incorrectly reuse the pre-cast pass).
    state, signal = priority.handle_pass(state, "player_2")
    assert signal == "CONTINUE", \
        "A single pass right after a new cast must not immediately resolve"
    print("PASS: test_casting_resets_the_pass_counter")


# ---------------------------------------------------------------------------
# Full scenario: priority returns to AP after a resolve, once the loop
# restarts via start_priority_window() again (the actual resolution
# logic itself belongs to Stage 3, so this test just proves the window
# resets correctly when called again).
# ---------------------------------------------------------------------------

def test_priority_returns_to_active_player_when_window_reopens():
    fake_item = {"stack_item_id": "stk_03", "item_type": "SPELL",
                 "source": "lightning_bolt_002", "targets": ["player_2"],
                 "controller": "player_2"}
    # active_player is player_1, but player_2 is the one who cast and
    # will be the one whose pass ends up triggering RESOLVE.
    state = _fresh_state(active_player="player_1")
    state = priority.start_priority_window(state)  # player_1 holds priority first
    state, _ = priority.handle_pass(state, "player_1")  # player_1 passes
    state = priority.handle_stack_action(state, fake_item)  # player_2 casts
    state, _ = priority.handle_pass(state, "player_2")  # player_2 passes
    state, signal = priority.handle_pass(state, "player_1")  # player_1 passes
    assert signal == "RESOLVE"

    # Once Stage 3's resolution logic finishes, the loop calls
    # start_priority_window() again -- confirm THAT always goes back
    # to the Active Player, regardless of who passed last (it was
    # player_1 here).
    state = priority.start_priority_window(state)
    assert state["priority_holder"] == "player_1"
    print("PASS: test_priority_returns_to_active_player_when_window_reopens")


if __name__ == "__main__":
    test_window_starts_with_active_player()
    test_first_pass_flips_priority_and_continues()
    test_both_pass_empty_stack_ends_step()
    test_both_pass_nonempty_stack_signals_resolve()
    test_passing_out_of_turn_raises()
    test_casting_pushes_stack_and_keeps_priority_with_caster()
    test_casting_resets_the_pass_counter()
    test_priority_returns_to_active_player_when_window_reopens()
    print("\nAll Stage 2 priority.py tests passed.")
