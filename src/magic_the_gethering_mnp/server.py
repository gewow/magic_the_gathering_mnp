"""
server.py

Wires together the modules the team already built and tested:
lobby.py, setup.py, mulligan.py, turn_manager.py, priority.py, sba.py,
card_effects.py, combat.py, game_state.py, pdu.py, framing.py.

KNOWN SCOPE LIMITATIONS (call these out in the README):
  - DISCARD at Cleanup (hand size > 7) is not yet enforced.
  - ASSIGN_DAMAGE_ORDER PDU is not yet requested from the client; if a
    multiply-blocked attacker occurs, damage_order defaults to
    combat.py's own fallback ordering instead of asking the player.
  - FIRST_STRIKE_DAMAGE step is always skipped (no first/double strike
    creatures in the current card pool).
  - TRIGGER_ORDER / TRIGGER_CHOICE are not yet wired in; triggers.py
    exists and is tested standalone but nothing calls detect_triggers()
    from this server loop yet.
  - seq_num is tracked and sent on every server PDU, but incoming
    client seq_nums are not yet validated against the priority token
    (STALE_ACTION is not yet enforced).
"""

import socket
import threading

from framing import recv_pdu, send_pdu, FramingError, ConnectionClosed
import pdu
import constants
import lobby
import setup
import mulligan
import turn_manager
import priority
import sba
import combat
import card_effects
import game_state

HOST = "0.0.0.0"
PORT = 4444
MAX_CLIENTS = 2

# A minimal card catalog for deck validation. Replace with a real
# cards.json load if/when one exists.
CARD_CATALOG = {
    "lightning_bolt_001": {}, "lightning_bolt_002": {}, "lightning_bolt_003": {},
    "shock_001": {}, "shock_002": {}, "goblin_guide_001": {},
    "mountain_001": {}, "mountain_002": {}, "mountain_003": {}, "mountain_004": {},
    "counterspell_001": {}, "counterspell_002": {},
    "gray_merchant_001": {}, "gray_merchant_002": {},
    "island_001": {}, "island_002": {}, "swamp_001": {}, "swamp_002": {}, "swamp_003": {},
}

lock = threading.Lock()
shutdown_event = threading.Event()

clients = []              # list of (conn, addr)
conn_to_player = {}        # conn -> player_id
player_to_conn = {}        # player_id -> conn

lobby_state = lobby.create_lobby_tracking()
state = game_state.create_initial_state()   # the single authoritative game state


# ---------------------------------------------------------------------------
# Small send helpers
# ---------------------------------------------------------------------------

def send_to_player(player_id, msg, label=None):
    conn = player_to_conn.get(player_id)
    if conn is None:
        return
    send_pdu(conn, msg, label=label or player_id)


def broadcast(msg):
    for conn, addr in list(clients):
        send_pdu(conn, msg, label=f"{addr[0]}:{addr[1]}")


def send_personalized_state_to_all():
    for player_id in list(player_to_conn.keys()):
        visible = game_state.personalize_state(state, player_id)
        update = pdu.build_game_state_update(game_state.next_seq_num(state), visible)
        send_to_player(player_id, update)


def send_personalized_state_to(player_id):
    visible = game_state.personalize_state(state, player_id)
    update = pdu.build_game_state_update(game_state.next_seq_num(state), visible)
    send_to_player(player_id, update)


# ---------------------------------------------------------------------------
# Turn engine glue: auto-advance through non-actionable phases, open a
# priority window on phases that need one, and hand off to combat.py at
# the right points.
# ---------------------------------------------------------------------------

def open_priority_window():
    global state
    state = priority.start_priority_window(state)
    grant = pdu.build_priority_grant(game_state.next_seq_num(state), state["priority_holder"])
    send_to_player(state["priority_holder"], grant)


def broadcast_phase_transition(from_phase, to_phase):
    msg = pdu.build_phase_transition(
        game_state.next_seq_num(state), from_phase, to_phase,
        state["active_player"], state["turn"]
    )
    broadcast(msg)


def advance_and_settle():
    """
    Repeatedly advance the phase until reaching one that needs either a
    priority window or a specific player action (DECLARE_ATTACKERS /
    DECLARE_BLOCKERS), handling automatic phases (UNTAP, CLEANUP,
    ASSIGN_DAMAGE_ORDER when not needed, FIRST_STRIKE_DAMAGE, COMBAT_DAMAGE)
    along the way.
    """
    global state

    while True:
        current = state["phase"]

        if current == "DECLARE_ATTACKERS":
            combat.init_combat(state)
            return  # wait for a DECLARE_ATTACKERS PDU from the Active Player

        if current == "DECLARE_BLOCKERS":
            return  # wait for a DECLARE_BLOCKERS PDU from the Non-Active Player

        if current == "ASSIGN_DAMAGE_ORDER":
            if combat.needs_damage_order(state):
                return  # wait for ASSIGN_DAMAGE_ORDER (not yet requested -- see file header)
            from_phase = current
            state = turn_manager.advance_phase(state)
            broadcast_phase_transition(from_phase, state["phase"])
            continue

        if current == "FIRST_STRIKE_DAMAGE":
            from_phase = current
            state = turn_manager.advance_phase(state)
            broadcast_phase_transition(from_phase, state["phase"])
            continue

        if current == "COMBAT_DAMAGE":
            new_state, damage_events, creatures_died = combat.resolve_combat_damage(state)
            state = new_state
            result_msg = pdu.build_combat_damage_result(
                game_state.next_seq_num(state), damage_events,
                dict(state["life_totals"]), creatures_died
            )
            broadcast(result_msg)
            combat.clear_combat(state)
            if check_and_handle_game_over():
                return
            from_phase = current
            state = turn_manager.advance_phase(state)
            broadcast_phase_transition(from_phase, state["phase"])
            continue

        if current in constants.PRIORITY_PHASES:
            open_priority_window()
            return

        # UNTAP, CLEANUP -- fully automatic, no priority, no player action
        from_phase = current
        state = turn_manager.advance_phase(state)
        broadcast_phase_transition(from_phase, state["phase"])
        # loop continues


def check_and_handle_game_over():
    """Run SBAs; if a game-over condition is found, broadcast GAME_OVER
    and reset back to LOBBY. Returns True if the game ended."""
    global state, lobby_state
    new_state, events, game_over_event = sba.run_sba_until_stable(state)
    state = new_state
    if game_over_event:
        winner = game_over_event["winner"]
        loser = game_over_event["loser"]
        msg = pdu.build_game_over(game_state.next_seq_num(state), winner, loser, "LIFE_ZERO")
        broadcast(msg)
        reset_to_lobby()
        return True
    if events:
        send_personalized_state_to_all()
    return False


def reset_to_lobby():
    global state, lobby_state

    # Preserve the server sequence counter
    old_server_seq = state["_server_seq_num"]

    lobby_state = lobby.create_lobby_tracking()
    state = game_state.create_initial_state()

    # Restore it
    state["_server_seq_num"] = old_server_seq


def begin_first_turn():
    """Called once both players have kept their mulligan hands."""
    global state
    state["turn"] = 1
    state["phase"] = "UNTAP"
    advance_and_settle()


# ---------------------------------------------------------------------------
# Per-connection handler
# ---------------------------------------------------------------------------

def handle_client(conn, addr):
    global clients, lobby_state, state

    label = f"{addr[0]}:{addr[1]}"
    conn.settimeout(1.0)

    try:
        while not shutdown_event.is_set():
            try:
                msg = recv_pdu(conn, label=label)
            except socket.timeout:
                continue
            except FramingError:
                err = pdu.build_error(0, constants.ERROR_INVALID_JSON, "Malformed JSON received")
                send_pdu(conn, err, label=label)
                continue
            except ConnectionClosed:
                break
            except ConnectionError:
                break

            msg_type = msg.get("type")

            with lock:
                # -----------------------------------------------------
                # PING / PONG -- always allowed, any phase
                # -----------------------------------------------------
                if msg_type == "PING":
                    pong = pdu.build_pong(msg.get("seq_num"), msg.get("timestamp"))
                    send_pdu(conn, pong, label=label)
                    continue

                # -----------------------------------------------------
                # CONCEDE -- always allowed, any phase
                # -----------------------------------------------------
                if msg_type == "CONCEDE":
                    conceding = conn_to_player.get(conn)
                    if conceding is None:
                        continue

                    winner = turn_manager.other_player(conceding)
                    over = pdu.build_game_over(
                        game_state.next_seq_num(state),
                        winner,
                        conceding,
                        "CONCEDE"
                    )
                    broadcast(over)

                    reset_to_lobby()

                    # Tell everyone we're back in the lobby
                    connected_ids = list(player_to_conn.keys())
                    lobby_broadcast = lobby.build_lobby_broadcast(
                        lobby_state,
                        connected_ids,
                    )

                    update = pdu.build_game_state_update(
                        game_state.next_seq_num(state),
                        lobby_broadcast,
                    )

                    broadcast(update)
                    continue

                # -----------------------------------------------------
                # PLAYER_READY -- LOBBY phase
                # -----------------------------------------------------
                if msg_type == "PLAYER_READY":
                    player_id = msg.get("player_id")
                    deck_list = msg.get("deck_list", [])

                    new_lobby_state, err_code = lobby.process_player_ready(
                        lobby_state, player_id, deck_list, CARD_CATALOG, connection_id=label
                    )
                    if err_code:
                        err = pdu.build_error(msg.get("seq_num", 0), err_code,
                                               f"PLAYER_READY rejected: {err_code}", msg)
                        send_pdu(conn, err, label=label)
                        continue

                    lobby_state = new_lobby_state
                    conn_to_player[conn] = player_id
                    player_to_conn[player_id] = conn

                    if constants.is_verbose():
                        print(f"[SERVER] {player_id} is ready")

                    connected_ids = list(player_to_conn.keys())
                    lobby_broadcast = lobby.build_lobby_broadcast(lobby_state, connected_ids)
                    update = pdu.build_game_state_update(
                             game_state.next_seq_num(state),
                             lobby_broadcast)
                    broadcast(update)

                    if lobby.all_players_ready(lobby_state):
                        print("[SERVER] Both players ready. Starting game...")
                        ready_decks = lobby.ready_players_decklists(lobby_state)

                        # Preserve the server sequence counter
                        old_server_seq = state["_server_seq_num"]

                        state = setup.run_setup(ready_decks)

                        # Restore it into the new game state
                        state["_server_seq_num"] = old_server_seq

                        send_personalized_state_to_all()
                    continue

                # -----------------------------------------------------
                # MULLIGAN_CHOICE -- MULLIGAN phase
                # -----------------------------------------------------
                if msg_type == "MULLIGAN_CHOICE":
                    player_id = conn_to_player.get(conn)
                    if player_id is None:
                        continue

                    keep = msg.get("keep")
                    cards_to_bottom = msg.get("cards_to_bottom", [])

                    new_state, err_code = mulligan.mulligan_choice(
                        state, player_id, keep, cards_to_bottom
                    )
                    if err_code:
                        err = pdu.build_error(msg.get("seq_num", 0), err_code,
                                               "MULLIGAN_CHOICE rejected", msg)
                        send_pdu(conn, err, label=label)
                        continue

                    state = new_state

                    if state["phase_state"] == constants.IN_GAME:
                        print("[SERVER] Both players finished mulligan")
                        begin_first_turn()
                    else:
                        # Only the mulliganing/keeping player gets an
                        # updated GAME_STATE_UPDATE (RFC 6.4).
                        send_personalized_state_to(player_id)
                    continue

                # -----------------------------------------------------
                # Everything below requires IN_GAME
                # -----------------------------------------------------
                if state.get("phase_state") != constants.IN_GAME:
                    err = pdu.build_error(msg.get("seq_num", 0), constants.ERROR_WRONG_PHASE,
                                          f"{msg_type} not allowed outside IN_GAME", msg)
                    send_pdu(conn, err, label=label)
                    continue

                player_id = conn_to_player.get(conn)

                # -----------------------------------------------------
                # PRIORITY_PASS
                # -----------------------------------------------------
                if msg_type == "PRIORITY_PASS":
                    if player_id != state.get("priority_holder"):
                        err = pdu.build_error(msg.get("seq_num", 0), constants.ERROR_NOT_YOUR_PRIORITY,
                                              "You do not hold priority", msg)
                        send_pdu(conn, err, label=label)
                        continue

                    state, signal = priority.handle_pass(state, player_id)

                    if signal == "CONTINUE":
                        grant = pdu.build_priority_grant(game_state.next_seq_num(state), state["priority_holder"])
                        send_to_player(state["priority_holder"], grant)

                    elif signal == "STEP_END":
                        from_phase = state["phase"]
                        state = turn_manager.advance_phase(state)
                        broadcast_phase_transition(from_phase, state["phase"])
                        advance_and_settle()

                    elif signal == "RESOLVE":
                        state, resolve_event = priority.resolve_top_of_stack(
                            state, apply_effect_fn=card_effects.apply_card_effect
                        )
                        resolve_msg = pdu.build_stack_resolve(
                            game_state.next_seq_num(state), resolve_event["stack_item_id"],
                            resolve_event["result"], resolve_event["state_changes"]
                        )
                        broadcast(resolve_msg)
                        send_personalized_state_to_all()

                        if check_and_handle_game_over():
                            continue
                        open_priority_window()
                    continue

                # -----------------------------------------------------
                # CAST_SPELL
                # -----------------------------------------------------
                if msg_type == "CAST_SPELL":
                    if player_id != state.get("priority_holder"):
                        err = pdu.build_error(msg.get("seq_num", 0), constants.ERROR_NOT_YOUR_PRIORITY,
                                              "You do not hold priority", msg)
                        send_pdu(conn, err, label=label)
                        continue

                    card_id = msg.get("card_id")
                    targets = msg.get("targets", [])
                    stack_item = {
                        "stack_item_id": f"stk_{game_state.next_seq_num(state)}",
                        "item_type": "SPELL",
                        "source": card_id,
                        "targets": targets,
                        "controller": player_id,
                    }
                    if player_id in state["hands"] and card_id in state["hands"][player_id]:
                        state["hands"][player_id].remove(card_id)

                    state = priority.handle_stack_action(state, stack_item)
                    push_msg = pdu.build_stack_push(
                        game_state.next_seq_num(state), stack_item["stack_item_id"], "SPELL",
                        card_id, targets, player_id
                    )
                    broadcast(push_msg)
                    send_personalized_state_to_all()

                    grant = pdu.build_priority_grant(game_state.next_seq_num(state), player_id)
                    send_to_player(player_id, grant)
                    continue

                # -----------------------------------------------------
                # PLAY_LAND
                # -----------------------------------------------------
                if msg_type == "PLAY_LAND":
                    if player_id != state.get("priority_holder"):
                        err = pdu.build_error(msg.get("seq_num", 0), constants.ERROR_NOT_YOUR_PRIORITY,
                                              "You do not hold priority", msg)
                        send_pdu(conn, err, label=label)
                        continue
                    if state.get("land_played_this_turn"):
                        err = pdu.build_error(msg.get("seq_num", 0), constants.ERROR_ILLEGAL_ACTION,
                                              "A land has already been played this turn", msg)
                        send_pdu(conn, err, label=label)
                        continue

                    card_id = msg.get("card_id")
                    if card_id not in state["hands"].get(player_id, []):
                        err = pdu.build_error(msg.get("seq_num", 0), constants.ERROR_ILLEGAL_ACTION,
                                              "That card is not in your hand", msg)
                        send_pdu(conn, err, label=label)
                        continue

                    state["hands"][player_id].remove(card_id)
                    state["battlefield"].setdefault(player_id, []).append({"id": card_id, "tapped": False})
                    state["land_played_this_turn"] = True

                    send_personalized_state_to_all()
                    grant = pdu.build_priority_grant(game_state.next_seq_num(state), player_id)
                    send_to_player(player_id, grant)
                    continue

                # -----------------------------------------------------
                # DECLARE_ATTACKERS
                # -----------------------------------------------------
                if msg_type == "DECLARE_ATTACKERS":
                    if player_id != state["active_player"]:
                        err = pdu.build_error(msg.get("seq_num", 0), constants.ERROR_ILLEGAL_ACTION,
                                              "Only the Active Player declares attackers", msg)
                        send_pdu(conn, err, label=label)
                        continue
                    new_state, err_code = combat.declare_attackers(state, msg.get("attackers", []))
                    if err_code:
                        err = pdu.build_error(msg.get("seq_num", 0), err_code, "Illegal attackers", msg)
                        send_pdu(conn, err, label=label)
                        continue
                    state = new_state
                    send_personalized_state_to_all()
                    from_phase = state["phase"]
                    state = turn_manager.advance_phase(state)
                    broadcast_phase_transition(from_phase, state["phase"])
                    advance_and_settle()
                    continue

                # -----------------------------------------------------
                # DECLARE_BLOCKERS
                # -----------------------------------------------------
                if msg_type == "DECLARE_BLOCKERS":
                    defending = turn_manager.other_player(state["active_player"])
                    if player_id != defending:
                        err = pdu.build_error(msg.get("seq_num", 0), constants.ERROR_ILLEGAL_ACTION,
                                              "Only the Non-Active Player declares blockers", msg)
                        send_pdu(conn, err, label=label)
                        continue
                    new_state, err_code = combat.declare_blockers(state, msg.get("blockers", []))
                    if err_code:
                        err = pdu.build_error(msg.get("seq_num", 0), err_code, "Illegal blockers", msg)
                        send_pdu(conn, err, label=label)
                        continue
                    state = new_state
                    send_personalized_state_to_all()
                    from_phase = state["phase"]
                    state = turn_manager.advance_phase(state)
                    broadcast_phase_transition(from_phase, state["phase"])
                    advance_and_settle()
                    continue

                # -----------------------------------------------------
                # Unknown type
                # -----------------------------------------------------
                err = pdu.build_error(msg.get("seq_num", 0), constants.ERROR_UNKNOWN_TYPE,
                                      f"Unrecognized PDU type: {msg_type}", msg)
                send_pdu(conn, err, label=label)

    finally:
        if constants.is_verbose():
            print(f"[SERVER] Client disconnected: {addr}")
        conn.close()
        with lock:
            clients[:] = [c for c in clients if c[0] != conn]
            if conn in conn_to_player:
                del conn_to_player[conn]


def start_server(verbose=False):
    constants.set_verbose(verbose)

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((HOST, PORT))
    server_sock.listen()
    server_sock.settimeout(1.0)

    print(f"[SERVER] Listening on port {PORT}...")

    try:
        while not shutdown_event.is_set():
            try:
                conn, addr = server_sock.accept()
                conn.settimeout(1.0)
                label = f"{addr[0]}:{addr[1]}"

                with lock:
                    if len(clients) >= MAX_CLIENTS:
                        if constants.is_verbose():
                            print(f"[SERVER] Refusing connection from {addr} (server full)")
                        err = pdu.build_error(0, constants.ERROR_SERVER_FULL, "Only 2 clients allowed")
                        try:
                            send_pdu(conn, err, label=label)
                        except Exception:
                            pass
                        conn.close()
                        continue

                    clients.append((conn, addr))
                    if constants.is_verbose():
                        print(f"[SERVER] Accepted {addr} ({len(clients)}/2)")

                thread = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
                thread.start()

            except socket.timeout:
                continue

    except KeyboardInterrupt:
        print("\n[SERVER] Shutting down gracefully...")
        shutdown_event.set()

    for conn, addr in clients:
        try:
            conn.close()
        except Exception:
            pass

    server_sock.close()
    print("[SERVER] Shutdown complete.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    start_server(verbose=args.verbose)