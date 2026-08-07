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

        # --- seq_num / STALE_ACTION bookkeeping (RFC Section 5.4) ---
        # The seq_num of the most recent PRIORITY_GRANT issued. Any
        # priority-bearing PDU (CAST_SPELL, ACTIVATE_ABILITY,
        # PRIORITY_PASS, PLAY_LAND, ...) from the current priority
        # holder must echo this value.
        "_priority_seq": None,
        # The seq_num of the most recently broadcast PHASE_TRANSITION.
        # DECLARE_ATTACKERS / DECLARE_BLOCKERS / ASSIGN_DAMAGE_ORDER
        # must echo this value, since those PDUs are implicitly
        # requested by a PHASE_TRANSITION rather than a PRIORITY_GRANT.
        "_phase_transition_seq": None,
        # Per-player seq_num of the most recent GAME_STATE_UPDATE sent
        # to them during MULLIGAN (the initial hand or a post-redraw
        # hand). MULLIGAN_CHOICE must echo the value for that player.
        "_mulligan_request_seq": {},
        # The seq_num of the cleanup-time GAME_STATE_UPDATE that asked
        # the Active Player to discard down to 7 cards. None when no
        # discard is currently pending. DISCARD must echo this value.
        "_discard_request_seq": None,

        # --- triggered-ability flow bookkeeping (RFC Section 8.6) ---
        # Triggers currently detected and working their way through
        # TRIGGER_ORDER / TRIGGER_CHOICE before being pushed to the
        # stack. Cleared once the flow completes.
        "_pending_triggers": [],
        # player_id -> True while we're still waiting on that
        # player's TRIGGER_ORDER_RESPONSE (only set for players who
        # control 2+ simultaneous triggers).
        "_trigger_order_pending": {},
        # player_id -> seq_num of the TRIGGER_ORDER sent to them.
        "_trigger_order_seq": {},
        # player_id -> the ordered_trigger_ids list they supplied.
        "_trigger_order_responses": {},
        # trigger_id -> True while we're still waiting on that
        # optional trigger's TRIGGER_CHOICE_RESPONSE.
        "_trigger_choice_pending": {},
        # trigger_id -> seq_num of the TRIGGER_CHOICE sent.
        "_trigger_choice_seq": {},
        # trigger_id -> accept bool the controller supplied.
        "_trigger_choice_responses": {},
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
        "phase": (
            state["phase"]
            if state["phase_state"] == constants.IN_GAME
            else state["phase_state"]
        ),
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