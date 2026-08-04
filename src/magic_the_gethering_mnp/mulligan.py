import random 
import constants
import game_state

# Copies the state of the player before commencing mulligan, this is to protect original state. 
def copy_state(state:dict):
    newState=dict(state)
    newState["hands"]=dict(state["hands"])
    newState["hands"]=dict(state["hands"])
    newState["libraries"]=dict(state["libraries"])
    newState["mulligan_count"]=dict(state["mulligan_count"])
    newState["mulligan_kept"]=dict(state.get("mulligan_kept"), {})

    return newState

# Returns "True" when all players keep their cards/hand
def all_players_kept_cards(state:dict)->bool:
    player_ids=list(state["hands"].keys())

    if len(player_ids)==0:
        return False

    kept=state.get("mulligan_kept",{})
    for player_id in player_ids:
        if kept.get(player_id,False)==False:
            return False

    return True

# Ensures that the mulligan_count is consistent and is in the player's hand (This is a fail safe in case of tampering and messing with code)
# Note to self: Very important especially for online video games. 
def validate_bottom(hand: list, mulligan_count: int, cards_to_bottom: list)->bool:
    valid=True

    if len(cards_to_bottom)!=mulligan_count:
        valid=False
    else:
        remaining_hand=list(hand)
        for card_id in cards_to_bottom:
            if card_id in remaining_hand:
                remaining_hand.remove(card_id)
            else:
                valid=False
                break

    return valid

# Main mulligan function that returns the hand of the current player before drawing another 7 cards before adding to the mulligan_count.
def mulligan_choice(state: dict, player_id: str, keep:bool, cards_to_bottom:list)->tuple[dict,str|None]:
    flag=False
    error_code=None
    final_state=None

    hand = state["hands"].get(player_id,[])
    mulligan_count = state["mulligan_count"].get(player_id,0)

    if keep:
        valid = validate_bottom(hand,mulligan_count,cards_to_bottom)

        if not valid:
            flag=True
            error_code=constants.ERROR_ILLEGAL_ACTION
            final_state=state
        else:
            new_state = copy_state(state)

            new_hand=list(hand)
            for card_id in cards_to_bottom:
                new_hand.remove(card_id)
            new_state["hands"][player_id]=new_hand

            new_library=list(state["libraries"].get(player_id,[]))
            new_library.extend(cards_to_bottom)
            new_state["libraries"][player_id]=new_library

            new_state["mulligan_kept"][player_id]=True

            if all_players_kept_cards (new_state):
                new_state["phase_state"]=constants.IN_GAME

            final_state=new_state

    else:
        new_state = copy_state(state)

        current_hand=list(hand)
        current_library=list(state["libraries"].get(player_id, []))

        # London Style: Shuffles cards into the deck before getting 7 cards back 
        combined = current_hand + current_library
        random.shuffle(combined)

        new_hand = combined[: constants.STARTING_HAND_SIZE]
        new_library = combined[constants.STARTING_HAND_SIZE :]

        new_state["hands"][player_id] = new_hand
        new_state["libraries"][player_id] = new_library
        new_state["mulligan_count"][player_id]=mulligan_count + 1 # Don't forget to add one to the mulligan count.
        new_state["mulligan_kept"][player_id]=False

        final_state=new_state

    return final_state, error_code