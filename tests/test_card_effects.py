"""
test_card_effects.py — Member D's card effect test suite

Run with: python tests/test_card_effects.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                 "src", "magic_the_gethering_mnp"))

import card_effects  # noqa: E402
from mock_state import mock_precombat_main_state  # noqa: E402


def _stack_item(source: str, targets: list[str], controller: str = "player_1") -> dict:
    return {
        "stack_item_id": "stk_test",
        "source": source,
        "targets": targets,
        "controller": controller,
    }


def test_lightning_bolt_damages_player():
    state = mock_precombat_main_state()
    state, changes = card_effects.apply_card_effect(
        state, _stack_item("lightning_bolt_001", ["player_2"])
    )
    assert state["life_totals"]["player_2"] == 17
    assert changes == [{"type": "DAMAGE", "target": "player_2", "amount": 3}]
    print("PASS: test_lightning_bolt_damages_player")


def test_lightning_bolt_damages_creature():
    state = mock_precombat_main_state()
    state, changes = card_effects.apply_card_effect(
        state, _stack_item("lightning_bolt_001", ["goblin_guide_001"])
    )
    guide = next(p for p in state["battlefield"]["player_1"]
                 if p["id"] == "goblin_guide_001")
    assert guide["damage"] == 3
    assert changes[0]["amount"] == 3
    print("PASS: test_lightning_bolt_damages_creature")


def test_shock_damages_player():
    state = mock_precombat_main_state()
    state, changes = card_effects.apply_card_effect(
        state, _stack_item("shock_001", ["player_2"])
    )
    assert state["life_totals"]["player_2"] == 18
    assert changes == [{"type": "DAMAGE", "target": "player_2", "amount": 2}]
    print("PASS: test_shock_damages_player")


def test_counterspell_removes_target_from_stack():
    state = mock_precombat_main_state()
    state["stack"] = [
        {"stack_item_id": "stk_bolt", "source": "lightning_bolt_001",
         "targets": ["player_2"], "controller": "player_1"},
    ]
    state, changes = card_effects.apply_card_effect(
        state,
        {
            "stack_item_id": "stk_counter",
            "source": "counterspell_001",
            "targets": ["stk_bolt"],
            "controller": "player_2",
        },
    )
    assert state["stack"] == []
    assert changes == [{"type": "COUNTER", "target": "stk_bolt"}]
    print("PASS: test_counterspell_removes_target_from_stack")


def test_goblin_guide_enters_battlefield():
    state = mock_precombat_main_state()
    state["hands"]["player_1"].append("goblin_guide_002")
    state, changes = card_effects.apply_card_effect(
        state, _stack_item("goblin_guide_002", [], controller="player_1")
    )
    on_bf = [p for p in state["battlefield"]["player_1"]
             if p["id"] == "goblin_guide_002"]
    assert len(on_bf) == 1
    assert on_bf[0]["summoning_sick"] is True
    assert on_bf[0]["power"] == 2
    assert on_bf[0]["toughness"] == 2
    assert "goblin_guide_002" not in state["hands"]["player_1"]
    assert changes[0]["type"] == "PERMANENT_ENTERS"
    print("PASS: test_goblin_guide_enters_battlefield")


def test_gray_merchant_drain_with_devotion():
    state = mock_precombat_main_state()
    state["hands"]["player_2"].append("gray_merchant_001")
    state["battlefield"]["player_2"].append({"id": "swamp_003", "tapped": False})
    state, changes = card_effects.apply_card_effect(
        state,
        _stack_item("gray_merchant_001", [], controller="player_2"),
    )
    assert state["life_totals"]["player_2"] == 22
    assert state["life_totals"]["player_1"] == 18
    damage = [c for c in changes if c["type"] == "DAMAGE"]
    gain = [c for c in changes if c["type"] == "LIFE_GAIN"]
    assert len(damage) == 1 and damage[0]["amount"] == 2
    assert len(gain) == 1 and gain[0]["amount"] == 2
    print("PASS: test_gray_merchant_drain_with_devotion")


def test_unknown_card_is_no_op():
    state = mock_precombat_main_state()
    before = state["life_totals"]["player_2"]
    state, changes = card_effects.apply_card_effect(
        state, _stack_item("unknown_card_001", ["player_2"])
    )
    assert state["life_totals"]["player_2"] == before
    assert changes == []
    print("PASS: test_unknown_card_is_no_op")


if __name__ == "__main__":
    test_lightning_bolt_damages_player()
    test_lightning_bolt_damages_creature()
    test_shock_damages_player()
    test_counterspell_removes_target_from_stack()
    test_goblin_guide_enters_battlefield()
    test_gray_merchant_drain_with_devotion()
    test_unknown_card_is_no_op()
    print("\nAll card effect tests passed.")
