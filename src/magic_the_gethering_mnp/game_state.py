import constants

#Returns a fresh state dict for a brand new lobby
#Called once when the server starts, and again every time the server
#will return to lobby when game is over
def create_initial_state() -> dict:
    return {
        "phase_state": constants.LOBBY,
        "turn": 0,
        "phase": None,
        "active_player": None,
        "priority_holder": None,
        "life_totals": {},
        "hands": {},
        "libraries": {},
        "battlefield": {"player_1": [], "player_2": []},
        "graveyard": {"player_1": [], "player_2": []},
        "stack": [],
        "land_played_this_turn": False,
        "mulligan_count": {}, # Counts PER PLAYER how many times they mulliganed. 
        "mulligan_kept": {}, # Added to track if both players kept their cards to start the game. 
        "_server_seq_num": 0,
    }

def next_seq_num(state: dict) -> int:
    state["_server_seq_num"] += 1
    return state["_server_seq_num"]

def personalize_state(state: dict, viewer_id: str) -> dict:
    all_players = list(state["hands"].keys())
    opponent_ids = [p for p in all_players if p != viewer_id]

    hand_counts = {p: len(state["hands"].get(p, [])) for p in opponent_ids}
    library_counts = {p: len(state["libraries"].get(p, [])) for p in all_players}

    visible = {
        "turn": state["turn"],
        "phase": state["phase"],
        "active_player": state["active_player"],
        "priority_holder": state["priority_holder"],
        "life_totals": dict(state["life_totals"]),
        "hand": list(state["hands"].get(viewer_id, [])),
        "hand_counts": hand_counts,
        "library_counts": library_counts,
        "battlefield": {p: list(v) for p, v in state["battlefield"].items()},
        "graveyard": {p: list(v) for p, v in state["graveyard"].items()},
        "stack": list(state["stack"]),
        "land_played_this_turn": state["land_played_this_turn"],
    }
    return visible

def personalize_lobby_state(players_ready: int, waiting_for: list[str]) -> dict:
    return {
        "phase": constants.LOBBY,
        "players_ready": players_ready,
        "waiting_for": waiting_for,
    }