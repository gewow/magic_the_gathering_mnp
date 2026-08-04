import constants
import game_state

def create_lobby_tracking() -> dict:
    return {}

def validate_deck(deck_list, card_catalog):
    bFlag = False
    code = None

    if (len(deck_list) < constants.MIN_DECK_SIZE) or (len(deck_list) > constants.MAX_DECK_SIZE):
        bFlag = True

    else:
        for card_id in deck_list:
            if card_id not in card_catalog:
                bFlag = True
                break

    if bFlag:
        code = constants.ERROR_ILLEGAL_DECK

    return (not bFlag), code

def process_player_ready(lobby_state, player_id, deck_list, card_catalog, connection_id):
    bFlag = False
    final_state = None
    deck_status, deck_code = validate_deck(deck_list, card_catalog)

    # check if the deck is valid or whatever
    if (deck_status == False) and (deck_code == constants.ERROR_ILLEGAL_DECK):
        final_deck_code = constants.ERROR_ILLEGAL_DECK
        final_state = lobby_state
        bFlag = True
    else:
        # checks if the player is not a duplicate and the player exists
        player_info = lobby_state.get(player_id)
        if (player_info != None) and (player_info["connection_id"] != connection_id):
            final_deck_code = constants.ERROR_DUPLICATE_ID
            final_state = lobby_state
            bFlag = True

    if bFlag == False:
        new_state = dict(lobby_state)
        new_state[player_id] = {
            "deck_list": list(deck_list),
            "ready": True,
            "connection_id": connection_id,
        }
        final_state = new_state
        final_deck_code = None

    return final_state, final_deck_code
    
def all_players_ready(lobby_state):
    bReady = True

    if len(lobby_state) == 2:
        for player_id in lobby_state:
            if lobby_state[player_id]["ready"] == False:
                bReady = False
    else:
        bReady = False

    return bReady

def ready_players_decklists(lobby_state):
    card_state = {}

    if all_players_ready(lobby_state):
        for player_id in lobby_state:
            card_state[player_id] = lobby_state[player_id]["deck_list"]

    return card_state

def build_lobby_broadcast(lobby_state, connected_player_ids):
    players_ready = len(lobby_state)
    waiting_for = []
    for player_id in connected_player_ids:
        if player_id not in lobby_state:
            waiting_for.append(player_id)

    return game_state.personalize_lobby_state(players_ready, waiting_for)

def process_game_over(winner_id, loser_id, reason):
    new_message = {"type": constants.GAME_OVER, "winner_id": winner_id, "loser_id": loser_id, "reason": reason}
    new_lobby = create_lobby_tracking()
    new_state = game_state.create_initial_state()

    return new_message, new_lobby, new_state

