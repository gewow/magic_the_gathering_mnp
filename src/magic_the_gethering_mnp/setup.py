import random
import constants
import game_state

def run_setup(ready_players: dict) -> dict:
    state = game_state.create_initial_state()
    state["phase_state"] = constants.GAME_SETUP

    player_ids = list(ready_players.keys())

    state["battlefield"] = {}
    state["graveyard"] = {}

    for player_id in player_ids:
        deck = list(ready_players[player_id])
        random.shuffle(deck)
        state["hands"][player_id] = deck[: constants.STARTING_HAND_SIZE]
        state["libraries"][player_id] = deck[constants.STARTING_HAND_SIZE :]
        state["life_totals"][player_id] = constants.STARTING_LIFE
        state["mulligan_count"][player_id] = 0

        state["battlefield"][player_id] = []
        state["graveyard"][player_id] = []

    state["active_player"] = random.choice(player_ids)
    state["phase_state"] = constants.MULLIGAN

    return state