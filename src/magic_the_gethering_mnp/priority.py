import constants

def start_priority_window(state: dict) -> dict:
    #active player receives priority first
    state["priority_holder"] = state["active_player"]
    state["_pass_count"] = 0
    return state

def handle_pass(state: dict, player_id: str) -> tuple[dict, str]:
    #CONTINUE - priority passed to the other player, window stays open
    #STEP_END - both players passed consecutively, stack is empty
    #RESOLVE - both players passed consecutively with stack still having items

    if player_id != state["priority_holder"]:
        raise ValueError(
            f"{player_id} does not hold priority; "
            f" current holder is {state['priority_holder']}"
        )

    other_player = "player_2" if player_id == "player_1" else "player_1"

    state["_pass_count"] += 1
    state["priority_holder"] = other_player

    if state["_pass_count"] >= 2:
        if len(state["stack"]) == 0:
            return state, "STEP_END"
        else:
            return state, "RESOLVE"
        
    return state, "CONTINUE"


def handle_stack_action(state: dict, stack_item: dict) -> dict:
    #caster retains priority
    #resets pass in a row counter

    state["stack"].append(stack_item)
    state["_pass_count"] = 0

    state["priority_holder"] = stack_item["controller"]
    return state