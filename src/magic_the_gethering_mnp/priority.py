import constants
import sba

def start_priority_window(state: dict) -> dict:
    #active player receives priority first
    state["priority_holder"] = state["active_player"]
    state["_pass_count"] = 0
    return state

def handle_pass(state: dict, player_id: str) -> tuple[dict, str]:
    #CONTINUE - priority passed to the other player, window stays open
    #STEP_END - both players passed consecutively, stack is empty
    #RESOLVE - both players passed consecutively with stack still having items
    others = []

    if player_id != state["priority_holder"]:
        raise ValueError(
            f"{player_id} does not hold priority; "
            f" current holder is {state['priority_holder']}"
        )

    all_players = list(state["life_totals"].keys())

    for p in all_players:
        if p!= player_id:
            others.append(p)

    if len(others) != 1:
        raise ValueError(
            f"expected exactly one oppenent for {player_id!r}, "
            f"found {others!r} among {all_players!r}"
        )

    other_player = others[0]
    # other_player = "player_2" if player_id == "player_1" else "player_1"

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

def _is_target_legal(state, target):
    if target in state["life_totals"]:
        return True
    for permanents in state["battlefield"].values():
        if any(perm["id"] == target for perm in permanents):
            return True
    # A target can also be another item still on the stack (e.g.
    # Counterspell targets a spell, not a player or permanent). This
    # check happens AFTER the resolving item has already been popped,
    # so state["stack"] here correctly excludes the item resolving.
    if any(item["stack_item_id"] == target for item in state["stack"]):
        return True
    return False

def _find_permanent(state, permanent_id):
    for player_id, permanents in state["battlefield"].items():
        for permanent in permanents:
            if permanent.get("id") == permanent_id:
                return player_id, permanent

    return None

def _is_ability_target_legal(state, ability, target, controller):
    """
    Validate a target against the structured target definition
    stored in the activated ability's card-catalog entry.
    """

    target_info = ability.get("targets", {})
    target_type = target_info.get("type")
    required = target_info.get("required", False)

    # ---------------------------------------------------------
    # Ability does not require a target
    # ---------------------------------------------------------
    if not required or target_type == "NONE":
        return target is None

    # ---------------------------------------------------------
    # ANY
    # ---------------------------------------------------------
    if target_type == "ANY":
        return _is_target_legal(state, target)

    # ---------------------------------------------------------
    # PLAYER
    # ---------------------------------------------------------
    if target_type == "PLAYER":
        return target in state["life_totals"]

    # ---------------------------------------------------------
    # Find permanent for creature-specific targets
    # ---------------------------------------------------------
    found = _find_permanent(state, target)

    if found is None:
        return False

    permanent_controller, permanent = found

    # ---------------------------------------------------------
    # CREATURE_YOU_CONTROL
    # ---------------------------------------------------------
    if target_type == "CREATURE_YOU_CONTROL":
        return (
            permanent_controller == controller
            and permanent.get("power") is not None
            and permanent.get("toughness") is not None
        )

    # ---------------------------------------------------------
    # TAPPED_CREATURE
    # ---------------------------------------------------------
    if target_type == "TAPPED_CREATURE":
        return (
            permanent.get("power") is not None
            and permanent.get("toughness") is not None
            and permanent.get("tapped") is True
        )

    # ---------------------------------------------------------
    # Unknown target type
    # ---------------------------------------------------------
    return False

def resolve_top_of_stack(state, apply_effect_fn=None):
    if not state["stack"]:
        raise ValueError("resolve_top_of_stack called with an empty stack")

    stack_item = state["stack"].pop()
    targets = stack_item.get("targets", [])

    # If ALL targets are illegal, the item fizzles
    # multi-target spell with at least one still-legal target must
    # still resolve, not fizzle. Only fizzle when NONE of the declared
    # targets remain legal.
    if targets:
        legal_targets = [t for t in targets if _is_target_legal(state, t)]
        all_illegal = len(legal_targets) == 0
    else:
        all_illegal = False

    if targets and all_illegal:
        result = "FIZZLE"
        state_changes = []
    else:
        result = "RESOLVED"
        state_changes = []
        if apply_effect_fn is not None:
            state, state_changes = apply_effect_fn(state, stack_item)

    event = {
        "stack_item_id": stack_item["stack_item_id"],
        "result": result, 
        "state_changes": state_changes,
    }

    return state, event

def process_stack_and_sbas(state, apply_effect_fn = None):
    state, resolve_event = resolve_top_of_stack(state, apply_effect_fn)
    state, sba_events, game_over_event = sba.run_sba_until_stable(state)

    result = {
        "stack_resolve": resolve_event,
        "sba_events": sba_events,
        "game_over": game_over_event,
        "state": state
    }

    if game_over_event is None:
        result["next_priority_to"] = state["active_player"]

    return result