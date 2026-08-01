"""
test_lobby_and_setup.py — Member B's test suite

This file assumes lobby.py, setup.py, and mulligan.py expose the
following function signatures. If you design different signatures,
update this file to match — the important thing is that everyone
agrees on ONE version before other members build against it.

    lobby.validate_deck(deck_list: list[str], card_catalog: dict) -> tuple[bool, str|None]
        Returns (True, None) if legal, or (False, error_code) if not.

    lobby.process_player_ready(lobby_state: dict, player_id: str,
                                deck_list: list[str], card_catalog: dict) -> tuple[dict, str|None]
        lobby_state is a simple dict: {"ready_players": {player_id: deck_list, ...}}
        Returns (updated_lobby_state, error_code_or_None).

    setup.run_setup(ready_players: dict[str, list[str]]) -> dict
        Takes the two ready players' decks, returns a fully populated
        game_state.py-shaped state dict (life=20, hands dealt, shuffled
        libraries, active_player chosen by coin flip).

    mulligan.process_mulligan_choice(state: dict, player_id: str, keep: bool,
                                      cards_to_bottom: list[str]) -> tuple[dict, str|None]
        Returns (updated_state, error_code_or_None).

Run with: python3 tests/test_lobby_and_setup.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                 "src", "magic_the_gethering_mnp"))

import constants  # noqa: E402

try:
    import lobby
    import setup
    import mulligan
except ImportError as exc:
    print(f"Cannot run tests yet — {exc}")
    print("Build lobby.py / setup.py / mulligan.py with the function "
          "signatures documented at the top of this file, then re-run.")
    sys.exit(1)


# A small fake card catalog standing in for cards.json during unit tests.
FAKE_CATALOG = {
    "mountain_001": {}, "mountain_002": {}, "mountain_003": {},
    "lightning_bolt_001": {}, "lightning_bolt_002": {}, "shock_001": {},
    "goblin_guide_001": {}, "island_001": {}, "swamp_001": {},
    "counterspell_001": {},
}


# ---------------------------------------------------------------------------
# Deck validation
# ---------------------------------------------------------------------------

def test_valid_deck_accepted():
    deck = ["mountain_001", "mountain_002", "lightning_bolt_001"]
    ok, err = lobby.validate_deck(deck, FAKE_CATALOG)
    assert ok is True and err is None, f"Expected valid deck to pass, got {ok}, {err}"
    print("PASS: test_valid_deck_accepted")


def test_empty_deck_rejected():
    ok, err = lobby.validate_deck([], FAKE_CATALOG)
    assert ok is False and err == constants.ERROR_ILLEGAL_DECK
    print("PASS: test_empty_deck_rejected")


def test_oversized_deck_rejected():
    deck = ["mountain_001"] * 51
    ok, err = lobby.validate_deck(deck, FAKE_CATALOG)
    assert ok is False and err == constants.ERROR_ILLEGAL_DECK
    print("PASS: test_oversized_deck_rejected")


def test_unknown_card_id_rejected():
    deck = ["mountain_001", "not_a_real_card_999"]
    ok, err = lobby.validate_deck(deck, FAKE_CATALOG)
    assert ok is False and err == constants.ERROR_ILLEGAL_DECK
    print("PASS: test_unknown_card_id_rejected")


def test_exactly_50_cards_accepted():
    deck = ["mountain_001"] * 50
    ok, err = lobby.validate_deck(deck, FAKE_CATALOG)
    assert ok is True, "Exactly 50 cards is the legal maximum, must be accepted"
    print("PASS: test_exactly_50_cards_accepted")


# ---------------------------------------------------------------------------
# PLAYER_READY handling
# ---------------------------------------------------------------------------

def test_duplicate_player_id_rejected():
    lobby_state = {"ready_players": {}}
    deck = ["mountain_001", "lightning_bolt_001"]
    lobby_state, err = lobby.process_player_ready(lobby_state, "player_1", deck, FAKE_CATALOG)
    assert err is None
    lobby_state, err = lobby.process_player_ready(lobby_state, "player_1", deck, FAKE_CATALOG)
    assert err == constants.ERROR_DUPLICATE_ID, \
        "Second PLAYER_READY with the SAME id from a DIFFERENT connection must be rejected"
    print("PASS: test_duplicate_player_id_rejected")


def test_resubmission_by_same_player_replaces_deck():
    lobby_state = {"ready_players": {}}
    deck_a = ["mountain_001"]
    deck_b = ["mountain_002", "shock_001"]
    lobby_state, err1 = lobby.process_player_ready(lobby_state, "player_1", deck_a, FAKE_CATALOG)
    lobby_state, err2 = lobby.process_player_ready(lobby_state, "player_1", deck_b, FAKE_CATALOG)
    assert err1 is None and err2 is None, \
        "A player MAY resend PLAYER_READY before both are ready — must not be treated as duplicate"
    assert lobby_state["ready_players"]["player_1"] == deck_b, \
        "The newer deck submission must replace the older one"
    print("PASS: test_resubmission_by_same_player_replaces_deck")


# ---------------------------------------------------------------------------
# GAME_SETUP
# ---------------------------------------------------------------------------

def test_setup_life_totals_are_twenty():
    ready = {
        "player_1": ["mountain_001"] * 8,
        "player_2": ["island_001"] * 8,
    }
    state = setup.run_setup(ready)
    assert state["life_totals"] == {"player_1": 20, "player_2": 20}
    print("PASS: test_setup_life_totals_are_twenty")


def test_setup_deals_seven_card_hands():
    ready = {
        "player_1": ["mountain_001"] * 10,
        "player_2": ["island_001"] * 10,
    }
    state = setup.run_setup(ready)
    assert len(state["hands"]["player_1"]) == 7
    assert len(state["hands"]["player_2"]) == 7
    # 10 in deck - 7 drawn = 3 left in library
    assert len(state["libraries"]["player_1"]) == 3
    print("PASS: test_setup_deals_seven_card_hands")


def test_setup_coinflip_picks_a_valid_active_player():
    ready = {"player_1": ["mountain_001"] * 8, "player_2": ["island_001"] * 8}
    state = setup.run_setup(ready)
    assert state["active_player"] in ("player_1", "player_2")
    print("PASS: test_setup_coinflip_picks_a_valid_active_player")


def test_setup_coinflip_is_actually_random():
    """
    Statistical check: run setup 30 times, confirm BOTH players show up
    as the active player at least once. This does not prove fairness,
    but it catches the common bug of hardcoding player_1 as always first.
    """
    ready = {"player_1": ["mountain_001"] * 8, "player_2": ["island_001"] * 8}
    seen = set()
    for _ in range(30):
        state = setup.run_setup(ready)
        seen.add(state["active_player"])
    assert seen == {"player_1", "player_2"}, \
        f"Expected both players to win the coin flip across 30 trials, only saw: {seen}"
    print("PASS: test_setup_coinflip_is_actually_random")


# ---------------------------------------------------------------------------
# MULLIGAN
# ---------------------------------------------------------------------------

def test_keep_with_zero_mulligans_requires_empty_bottom():
    ready = {"player_1": ["mountain_001"] * 8, "player_2": ["island_001"] * 8}
    state = setup.run_setup(ready)
    state, err = mulligan.process_mulligan_choice(state, "player_1", keep=True,
                                                    cards_to_bottom=[])
    assert err is None
    print("PASS: test_keep_with_zero_mulligans_requires_empty_bottom")


def test_keep_with_wrong_bottom_count_rejected():
    ready = {"player_1": ["mountain_001"] * 8, "player_2": ["island_001"] * 8}
    state = setup.run_setup(ready)
    # Player has 0 mulligans so far — bottoming 1 card is illegal.
    a_card = state["hands"]["player_1"][0]
    state, err = mulligan.process_mulligan_choice(state, "player_1", keep=True,
                                                    cards_to_bottom=[a_card])
    assert err == constants.ERROR_ILLEGAL_ACTION
    print("PASS: test_keep_with_wrong_bottom_count_rejected")


def test_mulligan_redraws_seven_and_increments_count():
    ready = {"player_1": ["mountain_001"] * 10, "player_2": ["island_001"] * 8}
    state = setup.run_setup(ready)
    state, err = mulligan.process_mulligan_choice(state, "player_1", keep=False,
                                                    cards_to_bottom=[])
    assert err is None
    assert len(state["hands"]["player_1"]) == 7, "A mulligan redraws a fresh 7 cards"
    assert state["mulligan_count"]["player_1"] == 1
    print("PASS: test_mulligan_redraws_seven_and_increments_count")


def test_keep_after_one_mulligan_requires_exactly_one_bottomed():
    ready = {"player_1": ["mountain_001"] * 10, "player_2": ["island_001"] * 8}
    state = setup.run_setup(ready)
    state, _ = mulligan.process_mulligan_choice(state, "player_1", keep=False, cards_to_bottom=[])
    a_card = state["hands"]["player_1"][0]
    state, err = mulligan.process_mulligan_choice(state, "player_1", keep=True,
                                                    cards_to_bottom=[a_card])
    assert err is None, "Bottoming exactly 1 card after 1 mulligan must be accepted"
    assert len(state["hands"]["player_1"]) == 6, \
        "Hand should drop from 7 to 6 after bottoming 1 card"
    print("PASS: test_keep_after_one_mulligan_requires_exactly_one_bottomed")


if __name__ == "__main__":
    test_valid_deck_accepted()
    test_empty_deck_rejected()
    test_oversized_deck_rejected()
    test_unknown_card_id_rejected()
    test_exactly_50_cards_accepted()
    test_duplicate_player_id_rejected()
    test_resubmission_by_same_player_replaces_deck()
    test_setup_life_totals_are_twenty()
    test_setup_deals_seven_card_hands()
    test_setup_coinflip_picks_a_valid_active_player()
    test_setup_coinflip_is_actually_random()
    test_keep_with_zero_mulligans_requires_empty_bottom()
    test_keep_with_wrong_bottom_count_rejected()
    test_mulligan_redraws_seven_and_increments_count()
    test_keep_after_one_mulligan_requires_exactly_one_bottomed()
    print("\nAll lobby/setup/mulligan tests passed.")
