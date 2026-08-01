"""
test_combat.py — Member D's test suite (combat portion)

Assumed function signatures (update this file if your design differs):

    combat.declare_attackers(state: dict, attackers: list[dict]) -> tuple[dict, str|None]
        attackers: [{"creature_id": str, "target": str}, ...]
        Returns (updated_state, error_code_or_None). On success, each
        declared attacker's "tapped" becomes True.

    combat.declare_blockers(state: dict, blockers: list[dict]) -> tuple[dict, str|None]
        blockers: [{"creature_id": str, "blocking_id": str}, ...]
        Returns (updated_state, error_code_or_None). Blocking must NOT
        tap the blocker.

    combat.needs_damage_order(state: dict) -> bool
        True if any attacker this combat has 2+ blockers assigned.

    combat.resolve_combat_damage(state: dict, damage_order: dict[str, list[str]] = None) -> tuple[dict, list[dict], list[str]]
        damage_order: {attacker_id: [blocker_id, ...]} for any multiply-blocked attacker.
        Returns (updated_state, damage_events, creatures_died) where
        damage_events matches COMBAT_DAMAGE_RESULT's shape:
            [{"source": str, "target": str, "amount": int}, ...]

Run with: python3 tests/test_combat.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                 "src", "magic_the_gethering_mnp"))

import constants  # noqa: E402

try:
    import combat
except ImportError as exc:
    print(f"Cannot run tests yet — {exc}")
    print("Build combat.py with the function signatures documented at "
          "the top of this file, then re-run.")
    sys.exit(1)

from mock_state import mock_combat_state_with_blockers  # noqa: E402


# ---------------------------------------------------------------------------
# Declare Attackers
# ---------------------------------------------------------------------------

def test_summoning_sick_creature_cannot_attack():
    state = mock_combat_state_with_blockers()
    # Make goblin_guide_001 summoning sick for this test
    for permanent in state["battlefield"]["player_1"]:
        if permanent["id"] == "goblin_guide_001":
            permanent["summoning_sick"] = True
    state, err = combat.declare_attackers(
        state, [{"creature_id": "goblin_guide_001", "target": "player_2"}]
    )
    assert err == constants.ERROR_ILLEGAL_ACTION
    print("PASS: test_summoning_sick_creature_cannot_attack")


def test_tapped_creature_cannot_attack():
    state = mock_combat_state_with_blockers()
    for permanent in state["battlefield"]["player_1"]:
        if permanent["id"] == "goblin_guide_001":
            permanent["tapped"] = True
    state, err = combat.declare_attackers(
        state, [{"creature_id": "goblin_guide_001", "target": "player_2"}]
    )
    assert err == constants.ERROR_ILLEGAL_ACTION
    print("PASS: test_tapped_creature_cannot_attack")


def test_declaring_attacker_taps_it():
    state = mock_combat_state_with_blockers()
    state, err = combat.declare_attackers(
        state, [{"creature_id": "goblin_guide_001", "target": "player_2"}]
    )
    assert err is None
    attacker = next(p for p in state["battlefield"]["player_1"]
                     if p["id"] == "goblin_guide_001")
    assert attacker["tapped"] is True
    print("PASS: test_declaring_attacker_taps_it")


def test_empty_attackers_array_is_legal():
    state = mock_combat_state_with_blockers()
    state, err = combat.declare_attackers(state, [])
    assert err is None, "Declaring no attackers must be legal, not an error"
    print("PASS: test_empty_attackers_array_is_legal")


# ---------------------------------------------------------------------------
# Declare Blockers
# ---------------------------------------------------------------------------

def test_blocking_does_not_tap_blocker():
    state = mock_combat_state_with_blockers()
    state, _ = combat.declare_attackers(
        state, [{"creature_id": "reckless_wurm_003", "target": "player_2"}]
    )
    state, err = combat.declare_blockers(
        state, [{"creature_id": "wall_of_stone_004", "blocking_id": "reckless_wurm_003"}]
    )
    assert err is None
    blocker = next(p for p in state["battlefield"]["player_2"]
                   if p["id"] == "wall_of_stone_004")
    assert blocker["tapped"] is False, "Declaring a block must not tap the blocker"
    print("PASS: test_blocking_does_not_tap_blocker")


def test_multiple_blockers_triggers_damage_order_requirement():
    state = mock_combat_state_with_blockers()
    state, _ = combat.declare_attackers(
        state, [{"creature_id": "reckless_wurm_003", "target": "player_2"}]
    )
    # Only one blocker exists in the mock state, so this test documents
    # the expected behavior for when 2+ block one attacker.
    # Extend mock_state.py with a second blocker to fully exercise this.
    single_block = [{"creature_id": "wall_of_stone_004", "blocking_id": "reckless_wurm_003"}]
    state, _ = combat.declare_blockers(state, single_block)
    assert combat.needs_damage_order(state) is False, \
        "A single blocker on an attacker should NOT require damage ordering"
    print("PASS: test_multiple_blockers_triggers_damage_order_requirement "
          "(single-block case only — extend mock_state for a true multi-block test)")


# ---------------------------------------------------------------------------
# Combat Damage
# ---------------------------------------------------------------------------

def test_unblocked_attacker_damages_player():
    state = mock_combat_state_with_blockers()
    state, _ = combat.declare_attackers(
        state, [{"creature_id": "goblin_guide_001", "target": "player_2"}]
    )
    state, _ = combat.declare_blockers(state, [])  # no blocks at all
    state, damage_events, creatures_died = combat.resolve_combat_damage(state)
    matching = [e for e in damage_events
                if e["source"] == "goblin_guide_001" and e["target"] == "player_2"]
    assert len(matching) == 1 and matching[0]["amount"] == 2, \
        "Unblocked Goblin Guide (power 2) must deal 2 damage directly to player_2"
    print("PASS: test_unblocked_attacker_damages_player")


def test_blocked_attacker_never_damages_player_no_trample():
    state = mock_combat_state_with_blockers()
    state, _ = combat.declare_attackers(
        state, [{"creature_id": "reckless_wurm_003", "target": "player_2"}]
    )
    state, _ = combat.declare_blockers(
        state, [{"creature_id": "wall_of_stone_004", "blocking_id": "reckless_wurm_003"}]
    )
    state, damage_events, creatures_died = combat.resolve_combat_damage(state)
    to_player = [e for e in damage_events if e["target"] == "player_2"]
    assert to_player == [], \
        "MTGNP 1.0 has no trample — a blocked attacker must deal 0 damage to the player"
    to_blocker = [e for e in damage_events if e["target"] == "wall_of_stone_004"]
    assert len(to_blocker) == 1 and to_blocker[0]["amount"] == 6
    print("PASS: test_blocked_attacker_never_damages_player_no_trample")


def test_lethal_damage_kills_creature():
    state = mock_combat_state_with_blockers()
    # Give the wall only 4 toughness worth of buffer this time via damage already marked
    for p in state["battlefield"]["player_2"]:
        if p["id"] == "wall_of_stone_004":
            p["toughness"] = 4  # attacker deals 6, now lethal
    state, _ = combat.declare_attackers(
        state, [{"creature_id": "reckless_wurm_003", "target": "player_2"}]
    )
    state, _ = combat.declare_blockers(
        state, [{"creature_id": "wall_of_stone_004", "blocking_id": "reckless_wurm_003"}]
    )
    state, damage_events, creatures_died = combat.resolve_combat_damage(state)
    assert "wall_of_stone_004" in creatures_died
    print("PASS: test_lethal_damage_kills_creature")


if __name__ == "__main__":
    test_summoning_sick_creature_cannot_attack()
    test_tapped_creature_cannot_attack()
    test_declaring_attacker_taps_it()
    test_empty_attackers_array_is_legal()
    test_blocking_does_not_tap_blocker()
    test_multiple_blockers_triggers_damage_order_requirement()
    test_unblocked_attacker_damages_player()
    test_blocked_attacker_never_damages_player_no_trample()
    test_lethal_damage_kills_creature()
    print("\nAll combat.py tests passed.")
