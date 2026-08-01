"""
mock_state.py

Hand-built game_state dicts that follow the exact schema defined in
game_state.py, but skip actually running LOBBY/GAME_SETUP/MULLIGAN to
produce them. Use these to unit-test priority.py, sba.py, combat.py,
and triggers.py in isolation, before B's real lobby/setup code exists.

These are NOT fakes with different behavior — they are real state
dicts, just constructed by hand instead of by playing through the
early game. Anything that consumes game_state.py's schema should
accept these without modification.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                 "src", "magic_the_gethering_mnp"))

import constants  # noqa: E402


def mock_precombat_main_state() -> dict:
    """
    A state resembling Turn 1, Precombat Main, right after Player 1
    has cast Goblin Guide (matches Step 16 of the sample PDU exchange).
    Useful for testing CAST_SPELL / stack push-resolve logic.
    """
    return {
        "phase_state": constants.IN_GAME,
        "turn": 1,
        "phase": "PRECOMBAT_MAIN",
        "active_player": "player_1",
        "priority_holder": "player_1",
        "life_totals": {"player_1": 20, "player_2": 20},
        "hands": {
            "player_1": ["lightning_bolt_001", "shock_001", "lightning_bolt_002"],
            "player_2": ["counterspell_001", "gray_merchant_001", "island_002",
                         "swamp_002", "counterspell_002", "gray_merchant_002"],
        },
        "libraries": {"player_1": ["mountain_004"], "player_2": ["swamp_003"]},
        "battlefield": {
            "player_1": [
                {"id": "mountain_003", "tapped": False},
                {"id": "goblin_guide_001", "tapped": False, "damage": 0,
                 "power": 2, "toughness": 2, "summoning_sick": True},
            ],
            "player_2": [],
        },
        "graveyard": {"player_1": [], "player_2": []},
        "stack": [],
        "land_played_this_turn": True,
        "mulligan_count": {"player_1": 0, "player_2": 1},
        "_server_seq_num": 19,
    }


def mock_combat_state_with_blockers() -> dict:
    """
    A state where Player 1 has two untapped attackers and Player 2 has
    one untapped blocker, useful for testing combat.py's declare
    attackers/blockers/damage assignment without needing to reach this
    point via a real game.
    """
    return {
        "phase_state": constants.IN_GAME,
        "turn": 4,
        "phase": "DECLARE_ATTACKERS",
        "active_player": "player_1",
        "priority_holder": None,
        "life_totals": {"player_1": 20, "player_2": 14},
        "hands": {"player_1": [], "player_2": ["counterspell_001"]},
        "libraries": {"player_1": [], "player_2": []},
        "battlefield": {
            "player_1": [
                {"id": "goblin_guide_001", "tapped": False, "damage": 0,
                 "power": 2, "toughness": 2, "summoning_sick": False},
                {"id": "reckless_wurm_003", "tapped": False, "damage": 0,
                 "power": 6, "toughness": 4, "summoning_sick": False},
            ],
            "player_2": [
                {"id": "wall_of_stone_004", "tapped": False, "damage": 0,
                 "power": 0, "toughness": 8, "summoning_sick": False},
            ],
        },
        "graveyard": {"player_1": [], "player_2": []},
        "stack": [],
        "land_played_this_turn": True,
        "mulligan_count": {"player_1": 0, "player_2": 0},
        "_server_seq_num": 55,
    }


def mock_lethal_state() -> dict:
    """
    Player 2 at 3 life, about to take exactly 3 damage — useful for
    testing sba.py's LIFE_ZERO win-condition detection in isolation.
    """
    return {
        "phase_state": constants.IN_GAME,
        "turn": 7,
        "phase": "PRECOMBAT_MAIN",
        "active_player": "player_1",
        "priority_holder": "player_1",
        "life_totals": {"player_1": 14, "player_2": 3},
        "hands": {"player_1": ["lightning_bolt_003"], "player_2": ["counterspell_001"]},
        "libraries": {"player_1": [], "player_2": []},
        "battlefield": {
            "player_1": [
                {"id": "mountain_001", "tapped": False},
                {"id": "mountain_002", "tapped": False},
                {"id": "mountain_003", "tapped": False},
                {"id": "goblin_guide_001", "tapped": False, "damage": 0,
                 "power": 2, "toughness": 2, "summoning_sick": False},
            ],
            "player_2": [
                {"id": "swamp_001", "tapped": False},
                {"id": "island_001", "tapped": False},
            ],
        },
        "graveyard": {"player_1": [], "player_2": []},
        "stack": [],
        "land_played_this_turn": False,
        "mulligan_count": {"player_1": 0, "player_2": 0},
        "_server_seq_num": 118,
    }
