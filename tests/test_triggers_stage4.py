"""
test_triggers_stage4.py

Tests ONLY what Stage 4 built: detect_triggers(),
filter_accepted_optional_triggers(), and build_trigger_push_order().
No dependency on a real card catalog -- uses fake trigger_catalog
fixtures, matching how priority.py's Stage 3 tests use fake
apply_effect_fn functions instead of real card effects.

Run with: python3 tests/test_triggers_stage4.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                 "src", "magic_the_gethering_mnp"))

import triggers  # noqa: E402


def _fresh_state(active_player="player_1"):
    return {
        "active_player": active_player,
        "battlefield": {
            "player_1": [{"id": "goblin_guide_001", "tapped": False,
                          "power": 2, "toughness": 2, "damage": 0,
                          "summoning_sick": False}],
            "player_2": [{"id": "wall_of_stone_004", "tapped": False,
                          "power": 0, "toughness": 8, "damage": 0,
                          "summoning_sick": False}],
        },
    }


# ---------------------------------------------------------------------------
# detect_triggers
# ---------------------------------------------------------------------------

def test_detect_triggers_returns_empty_without_a_catalog():
    state = _fresh_state()
    event = {"type": "PERMANENT_ENTERS", "card_id": "goblin_guide_001"}
    pending = triggers.detect_triggers(state, event, trigger_catalog=None)
    assert pending == [], "No catalog means no triggers fire, not a crash"
    print("PASS: test_detect_triggers_returns_empty_without_a_catalog")


def test_detect_triggers_finds_matching_trigger():
    state = _fresh_state()
    event = {"type": "COMBAT_DAMAGE_DEALT", "source": "goblin_guide_001"}

    fake_catalog = {
        "goblin_guide_001": [{
            "condition_fn": lambda ev, perm, st: ev["type"] == "COMBAT_DAMAGE_DEALT"
                                                  and ev["source"] == perm["id"],
            "optional": False,
            "requires_target": False,
            "effect_summary": "When this deals combat damage, opponent reveals top card.",
        }],
    }

    pending = triggers.detect_triggers(state, event, trigger_catalog=fake_catalog)
    assert len(pending) == 1
    assert pending[0]["source_id"] == "goblin_guide_001"
    assert pending[0]["controller"] == "player_1"
    assert pending[0]["optional"] is False
    print("PASS: test_detect_triggers_finds_matching_trigger")


def test_detect_triggers_ignores_non_matching_permanents():
    state = _fresh_state()
    event = {"type": "COMBAT_DAMAGE_DEALT", "source": "goblin_guide_001"}
    fake_catalog = {
        "wall_of_stone_004": [{
            "condition_fn": lambda ev, perm, st: False,  # never fires
            "optional": False,
        }],
    }
    pending = triggers.detect_triggers(state, event, trigger_catalog=fake_catalog)
    assert pending == []
    print("PASS: test_detect_triggers_ignores_non_matching_permanents")


# ---------------------------------------------------------------------------
# filter_accepted_optional_triggers
# ---------------------------------------------------------------------------

def test_mandatory_triggers_always_pass_through():
    pending = [{"trigger_id": "trg_01", "optional": False}]
    result = triggers.filter_accepted_optional_triggers(pending, optional_responses={})
    assert result == pending
    print("PASS: test_mandatory_triggers_always_pass_through")


def test_accepted_optional_trigger_passes_through():
    pending = [{"trigger_id": "trg_02", "optional": True}]
    result = triggers.filter_accepted_optional_triggers(
        pending, optional_responses={"trg_02": True}
    )
    assert result == pending
    print("PASS: test_accepted_optional_trigger_passes_through")


def test_declined_optional_trigger_is_dropped():
    pending = [{"trigger_id": "trg_02", "optional": True}]
    result = triggers.filter_accepted_optional_triggers(
        pending, optional_responses={"trg_02": False}
    )
    assert result == [], "A declined optional trigger must be silently dropped"
    print("PASS: test_declined_optional_trigger_is_dropped")


def test_missing_optional_response_raises():
    pending = [{"trigger_id": "trg_02", "optional": True}]
    try:
        triggers.filter_accepted_optional_triggers(pending, optional_responses={})
        raised = False
    except ValueError:
        raised = True
    assert raised, "Missing a response for an optional trigger must raise"
    print("PASS: test_missing_optional_response_raises")


# ---------------------------------------------------------------------------
# build_trigger_push_order
# ---------------------------------------------------------------------------

def test_single_trigger_each_ap_pushed_before_nap():
    state = _fresh_state(active_player="player_1")
    pending = [
        {"trigger_id": "trg_nap", "controller": "player_2"},
        {"trigger_id": "trg_ap", "controller": "player_1"},
    ]
    ordered = triggers.build_trigger_push_order(state, pending)
    ids_in_order = [t["trigger_id"] for t in ordered]
    assert ids_in_order == ["trg_ap", "trg_nap"], \
        "AP's trigger must be pushed first (bottom), NAP's second (top)"
    print("PASS: test_single_trigger_each_ap_pushed_before_nap")


def test_two_simultaneous_triggers_same_player_requires_ordering():
    state = _fresh_state(active_player="player_1")
    pending = [
        {"trigger_id": "trg_03", "controller": "player_1"},
        {"trigger_id": "trg_04", "controller": "player_1"},
    ]
    try:
        triggers.build_trigger_push_order(state, pending, ordering_responses=None)
        raised = False
    except ValueError:
        raised = True
    assert raised, \
        "Two simultaneous triggers for one player without an ordering response must raise"
    print("PASS: test_two_simultaneous_triggers_same_player_requires_ordering")


def test_ordering_response_matches_rfc_worked_example():
    """
    Mirrors RFC 8.6.2's own worked example exactly: player wants trg_04
    placed on the stack first (so trg_03 resolves first, being on top).
    """
    state = _fresh_state(active_player="player_1")
    pending = [
        {"trigger_id": "trg_03", "controller": "player_1"},
        {"trigger_id": "trg_04", "controller": "player_1"},
    ]
    ordered = triggers.build_trigger_push_order(
        state, pending, ordering_responses={"player_1": ["trg_04", "trg_03"]}
    )
    ids_in_order = [t["trigger_id"] for t in ordered]
    assert ids_in_order == ["trg_04", "trg_03"], \
        "Must push in exactly the order the player specified"
    print("PASS: test_ordering_response_matches_rfc_worked_example")


def test_mismatched_ordering_response_raises():
    state = _fresh_state(active_player="player_1")
    pending = [
        {"trigger_id": "trg_03", "controller": "player_1"},
        {"trigger_id": "trg_04", "controller": "player_1"},
    ]
    try:
        triggers.build_trigger_push_order(
            state, pending,
            ordering_responses={"player_1": ["trg_04", "trg_99"]}  # trg_99 doesn't exist
        )
        raised = False
    except ValueError:
        raised = True
    assert raised, "An ordering response with the wrong trigger IDs must raise"
    print("PASS: test_mismatched_ordering_response_raises")


def test_mixed_single_and_multiple_across_both_players():
    """
    AP has 2 simultaneous triggers (needs ordering), NAP has just 1.
    Full result should be: [AP's ordered triggers..., NAP's single trigger].
    """
    state = _fresh_state(active_player="player_1")
    pending = [
        {"trigger_id": "trg_ap_1", "controller": "player_1"},
        {"trigger_id": "trg_ap_2", "controller": "player_1"},
        {"trigger_id": "trg_nap_1", "controller": "player_2"},
    ]
    ordered = triggers.build_trigger_push_order(
        state, pending,
        ordering_responses={"player_1": ["trg_ap_2", "trg_ap_1"]}
    )
    ids_in_order = [t["trigger_id"] for t in ordered]
    assert ids_in_order == ["trg_ap_2", "trg_ap_1", "trg_nap_1"], \
        f"Expected AP's ordered pair then NAP's single trigger, got {ids_in_order}"
    print("PASS: test_mixed_single_and_multiple_across_both_players")


if __name__ == "__main__":
    test_detect_triggers_returns_empty_without_a_catalog()
    test_detect_triggers_finds_matching_trigger()
    test_detect_triggers_ignores_non_matching_permanents()
    test_mandatory_triggers_always_pass_through()
    test_accepted_optional_trigger_passes_through()
    test_declined_optional_trigger_is_dropped()
    test_missing_optional_response_raises()
    test_single_trigger_each_ap_pushed_before_nap()
    test_two_simultaneous_triggers_same_player_requires_ordering()
    test_ordering_response_matches_rfc_worked_example()
    test_mismatched_ordering_response_raises()
    test_mixed_single_and_multiple_across_both_players()
    print("\nAll Stage 4 triggers.py tests passed.")
