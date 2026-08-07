import constants

def get_next_phase(current_phase: str) -> str:
    if current_phase not in constants.PHASE_ORDER:
        raise ValueError(f"Unknown phase: {current_phase}")

    index = constants.PHASE_ORDER.index(current_phase)
    next_index = (index + 1) % len(constants.PHASE_ORDER)
    return constants.PHASE_ORDER[next_index]

def other_player(state:dict, player_id: str) -> str:
    # return "player_2" if player_id == "player_1" else "player_1"
    others = []

    all_players = list(state["life_totals"].keys())

    for p in all_players:
        if p!= player_id:
            others.append(p)

    if len(others) != 1:
        raise ValueError(
            f"expected exactly one oppenent for {player_id!r}, "
            f"found {others!r} among {all_players!r}"
        )
    
    return others[0]


def advance_phase(state: dict) -> dict:
    current_phase = state["phase"]
    next_phase = get_next_phase(current_phase)

    if current_phase == "CLEANUP" and next_phase == "UNTAP":
        state["turn"] += 1
        state["active_player"] = other_player(state["active_player"])

    state["phase"] = next_phase
    return state