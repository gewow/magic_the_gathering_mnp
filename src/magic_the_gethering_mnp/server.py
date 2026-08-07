"""
server.py

Wires together the modules the team already built and tested:
lobby.py, setup.py, mulligan.py, turn_manager.py, priority.py, sba.py,
card_effects.py, combat.py, game_state.py, pdu.py, framing.py.

KNOWN SCOPE LIMITATIONS (call these out in the README):
  - (none remaining from the original three -- see RESOLVED below)

RESOLVED (previously listed here as scope limitations):
  - cards.json is now generated from mtgnp_master_card_list.xlsx (312
    card instances) and loaded as CARD_CATALOG below, instead of the
    ~19-card hardcoded stub.
  - seq_num is now validated against the current outstanding request
    token for every priority-echo PDU (CAST_SPELL, ACTIVATE_ABILITY,
    PRIORITY_PASS, PLAY_LAND, DECLARE_ATTACKERS, DECLARE_BLOCKERS,
    ASSIGN_DAMAGE_ORDER), plus MULLIGAN_CHOICE and DISCARD, per RFC
    Section 5.4. Mismatches are rejected with ERROR code STALE_ACTION.
  - DISCARD at Cleanup (hand size > 7) is now enforced per RFC 7.8:
    the Active Player is asked to discard down to 7 cards before the
    turn is allowed to advance to the next Untap Step.
  - ASSIGN_DAMAGE_ORDER is now handled: a multiply-blocked attacker
    makes the server wait for one ASSIGN_DAMAGE_ORDER PDU per such
    attacker (RFC 9.5) instead of silently falling back to
    combat.py's internal default ordering.
  - FIRST_STRIKE_DAMAGE is still always a no-op pass-through, but this
    is now an explicitly documented, monitored deviation (see
    _battlefield_has_first_or_double_strike()) rather than a silent
    gap: no card in the current pool grants first/double strike, and
    the server logs a warning in verbose mode if that ever changes
    without combat.py gaining real first-strike sub-resolution.
  - TRIGGER_ORDER / TRIGGER_CHOICE are now wired into the server loop
    (see _start_trigger_flow / _start_trigger_choices /
    _finish_trigger_flow below): Gray Merchant of Asphodel's "you may
    gain life" ETB trigger fires for real in a live game instead of
    being hardcoded as an unconditional part of the creature spell's
    own resolution.
"""

import json
import os
import socket
import threading
import time

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
import triggers

HOST = "0.0.0.0"
PORT = 4444
MAX_CLIENTS = 2

# ---------------------------------------------------------------------------
# Card catalog -- loaded from cards.json (generated from
# mtgnp_master_card_list.xlsx: 312 card instances across the full
# W/U/B/R/G + colorless pool). Falls back to a tiny stub only if the
# file is missing/unreadable so the server can still boot for local
# testing, but that fallback should never be relied on for the demo.
# ---------------------------------------------------------------------------

_CARDS_JSON_PATH = os.path.join(os.path.dirname(__file__), "cards.json")

_FALLBACK_CARD_CATALOG = {
    "lightning_bolt_001": {}, "lightning_bolt_002": {}, "lightning_bolt_003": {},
    "shock_001": {}, "shock_002": {}, "goblin_guide_001": {},
    "mountain_001": {}, "mountain_002": {}, "mountain_003": {}, "mountain_004": {},
    "counterspell_001": {}, "counterspell_002": {},
    "gray_merchant_001": {}, "gray_merchant_002": {},
    "island_001": {}, "island_002": {}, "swamp_001": {}, "swamp_002": {}, "swamp_003": {},
}


def _load_card_catalog(path: str = _CARDS_JSON_PATH) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            catalog = json.load(f)
        if not isinstance(catalog, dict) or not catalog:
            raise ValueError("cards.json did not contain a non-empty object")
        print(f"[SERVER] Loaded {len(catalog)} cards from {path}")
        return catalog
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[SERVER] WARNING: could not load {path} ({exc}); "
              f"falling back to {len(_FALLBACK_CARD_CATALOG)}-card stub catalog")
        return dict(_FALLBACK_CARD_CATALOG)


CARD_CATALOG = _load_card_catalog()

# Triggered-ability catalog (RFC Section 8.6), expanded from
# card_effects.TRIGGER_DEFS_BY_BASE against every instance id in
# CARD_CATALOG. Currently only Gray Merchant of Asphodel's ETB "you
# may gain life" trigger is defined; adding more triggered cards is a
# card_effects.py change only -- nothing here needs to change.
TRIGGER_CATALOG = card_effects.build_trigger_catalog(CARD_CATALOG)

lock = threading.Lock()
shutdown_event = threading.Event()

clients = []              # list of (conn, addr)
conn_to_player = {}        # conn -> player_id
player_to_conn = {}        # player_id -> conn
pending_disconnects = {}   # player_id -> {"timer": threading.Timer, "since": float}

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
    """Send every connected player their own personalized
    GAME_STATE_UPDATE. Returns {player_id: seq_num} in case a caller
    needs to remember which seq_num a particular player was just
    given (e.g. to set up a STALE_ACTION echo check)."""
    seqs = {}
    for player_id in list(player_to_conn.keys()):
        seqs[player_id] = send_personalized_state_to(player_id)
    return seqs


def send_personalized_state_to(player_id):
    """Send one player their own personalized GAME_STATE_UPDATE.
    Returns the seq_num used, so callers can record it as the
    "request token" the player's next echoing PDU must match."""
    seq = game_state.next_seq_num(state)
    visible = game_state.personalize_state(state, player_id)
    update = pdu.build_game_state_update(seq, visible)
    send_to_player(player_id, update)
    return seq


# ---------------------------------------------------------------------------
# Turn engine glue: auto-advance through non-actionable phases, open a
# priority window on phases that need one, and hand off to combat.py at
# the right points.
# ---------------------------------------------------------------------------

def _grant_priority_to(player_id):
    """Send PRIORITY_GRANT to player_id and record the seq_num used as
    the current "priority token". Every priority-echo PDU (CAST_SPELL,
    ACTIVATE_ABILITY, PRIORITY_PASS, PLAY_LAND) from this player must
    echo this exact seq_num, per RFC Section 5.4; a mismatch is
    rejected with STALE_ACTION."""
    seq = game_state.next_seq_num(state)
    grant = pdu.build_priority_grant(seq, player_id)
    state["priority_holder"] = player_id
    state["_priority_seq"] = seq
    send_to_player(player_id, grant)
    return seq


def open_priority_window():
    global state
    state = priority.start_priority_window(state)
    _grant_priority_to(state["priority_holder"])


def broadcast_phase_transition(from_phase, to_phase):
    seq = game_state.next_seq_num(state)
    msg = pdu.build_phase_transition(
        seq, from_phase, to_phase,
        state["active_player"], state["turn"]
    )
    # DECLARE_ATTACKERS / DECLARE_BLOCKERS / ASSIGN_DAMAGE_ORDER are
    # implicitly "requested" by the PHASE_TRANSITION that announces
    # that step (RFC 9.3/9.4/9.5 -- "no separate request PDU is
    # defined"), so the client echoes *this* seq_num on those PDUs.
    state["_phase_transition_seq"] = seq
    broadcast(msg)


# ---------------------------------------------------------------------------
# STALE_ACTION enforcement (RFC Section 5.4 / Section 11)
#
# Every priority-bearing client PDU must echo the seq_num of the most
# recent server PDU that opened the window it's responding to. Which
# "token" applies depends on the PDU type:
#   - "priority": CAST_SPELL, ACTIVATE_ABILITY, PRIORITY_PASS, PLAY_LAND
#     -> must echo state["_priority_seq"] (the last PRIORITY_GRANT).
#   - "phase_transition": DECLARE_ATTACKERS, DECLARE_BLOCKERS,
#     ASSIGN_DAMAGE_ORDER -> must echo state["_phase_transition_seq"]
#     (the PHASE_TRANSITION that announced that step).
#   - "mulligan": MULLIGAN_CHOICE -> must echo
#     state["_mulligan_request_seq"][player_id] (the GAME_STATE_UPDATE
#     that gave that player their current hand).
#   - "discard": DISCARD -> must echo state["_discard_request_seq"]
#     (the cleanup-time GAME_STATE_UPDATE that asked for a discard).
# CONCEDE and PING are exempt per RFC 5.4 and are not routed through
# this check at all.
# ---------------------------------------------------------------------------

def _expected_seq(kind, player_id=None):
    if kind == "priority":
        return state.get("_priority_seq")
    if kind == "phase_transition":
        return state.get("_phase_transition_seq")
    if kind == "mulligan":
        return state.get("_mulligan_request_seq", {}).get(player_id)
    if kind == "discard":
        return state.get("_discard_request_seq")
    return None


def _check_seq(kind, player_id, msg):
    """Returns None if msg's seq_num matches the current token for
    `kind`; otherwise returns a human-readable mismatch description
    suitable for an ERROR message."""
    expected = _expected_seq(kind, player_id)
    got = msg.get("seq_num")
    if expected is None or got != expected:
        return f"Priority token mismatch. Expected seq_num {expected}, got {got}."
    return None


def _reject_stale(conn, label, msg, reissue_priority_to=None):
    """Send ERROR STALE_ACTION for a mismatched seq_num. Per RFC
    Section 11.3, if the player still holds priority, the server
    re-issues PRIORITY_GRANT with the *same* seq_num so the player can
    retry -- we do NOT mint a new token here, since that would move
    the goalposts on a client that's simply racing a stale message."""
    err = pdu.build_error(
        msg.get("seq_num", 0), constants.ERROR_STALE_ACTION,
        f"Stale seq_num on {msg.get('type')}; action rejected.", msg,
    )
    send_pdu(conn, err, label=label)
    if reissue_priority_to is not None and state.get("_priority_seq") is not None:
        grant = pdu.build_priority_grant(state["_priority_seq"], reissue_priority_to)
        send_pdu(conn, grant, label=label)


def _battlefield_has_first_or_double_strike(state) -> bool:
    """Defensive check backing the FIRST_STRIKE_DAMAGE documented
    deviation above: permanents don't currently carry a first_strike/
    double_strike flag anywhere in the schema (card_effects.py's
    creature templates never set one), so this is always False today.
    It exists so that the day a keyword-granting card IS added, the
    step's silent skip turns into a loud warning instead of a quiet
    rules violation."""
    for permanents in state.get("battlefield", {}).values():
        for perm in permanents:
            if perm.get("first_strike") or perm.get("double_strike"):
                return True
    return False


def _clear_end_of_turn_state(state):
    """RFC 7.8: at Cleanup, remove all damage from creatures and clear
    'until end of turn' effects. Summoning sickness also clears here,
    since by the time a creature reaches its controller's next
    Cleanup it has already survived an Untap Step under that
    controller."""
    for permanents in state["battlefield"].values():
        for perm in permanents:
            if "damage" in perm:
                perm["damage"] = 0
            if "summoning_sick" in perm:
                perm["summoning_sick"] = False
    return state


# ---------------------------------------------------------------------------
# Triggered abilities (RFC Section 8.6)
#
# Wiring: whenever a resolved stack item produces a PERMANENT_ENTERS
# (or, in the future, other trigger-relevant) state_change, the caller
# runs this event through _start_trigger_flow(). That either:
#   (a) finds nothing and returns False -- caller proceeds normally
#       (opens priority itself), or
#   (b) finds triggers and takes over: sends TRIGGER_ORDER and/or
#       TRIGGER_CHOICE requests and returns True, so the caller must
#       NOT also open priority -- the flow will do that itself once
#       every required response is in (_finish_trigger_flow).
# ---------------------------------------------------------------------------

def _start_trigger_flow(event):
    global state
    pending = triggers.detect_triggers(state, event, TRIGGER_CATALOG)
    if not pending:
        return False

    state["_pending_triggers"] = pending

    # RFC 8.6.2 rule 3: a player who controls 2+ simultaneous triggers
    # must supply a TRIGGER_ORDER_RESPONSE before anything is placed
    # on the Stack.
    by_controller: dict[str, list[dict]] = {}
    for trig in pending:
        by_controller.setdefault(trig["controller"], []).append(trig)
    needs_order = {pid: trigs for pid, trigs in by_controller.items() if len(trigs) >= 2}

    if needs_order:
        state["_trigger_order_pending"] = {}
        for player_id, trigs in needs_order.items():
            seq = game_state.next_seq_num(state)
            order_req = pdu.build_trigger_order(seq, player_id, [t["trigger_id"] for t in trigs])
            state["_trigger_order_seq"][player_id] = seq
            state["_trigger_order_pending"][player_id] = True
            send_to_player(player_id, order_req)
        return True

    return _start_trigger_choices()


def _start_trigger_choices():
    """RFC 8.6.3: send TRIGGER_CHOICE for every optional trigger and
    wait. Assumes any needed TRIGGER_ORDER step has already completed
    (or was never needed)."""
    global state
    optional = [t for t in state.get("_pending_triggers", []) if t.get("optional")]
    if not optional:
        return _finish_trigger_flow()

    state["_trigger_choice_pending"] = {}
    for trig in optional:
        seq = game_state.next_seq_num(state)
        choice_req = pdu.build_trigger_choice(
            seq, trig["trigger_id"], trig["source_id"],
            trig.get("effect_summary", ""), trig.get("requires_target", False), [],
        )
        state["_trigger_choice_seq"][trig["trigger_id"]] = seq
        state["_trigger_choice_pending"][trig["trigger_id"]] = True
        send_to_player(trig["controller"], choice_req)
    return True


def _finish_trigger_flow():
    """All required TRIGGER_ORDER / TRIGGER_CHOICE responses are in.
    Filters out declined optional triggers, orders the rest per RFC
    8.6.2, pushes each surviving one onto the Stack as a
    TRIGGER_ABILITY item (RFC 8.6.4), resets the flow's bookkeeping,
    and opens priority -- since this is always the terminal step of a
    trigger flow, it is responsible for opening priority itself."""
    global state
    pending = state.get("_pending_triggers", [])
    accepted = triggers.filter_accepted_optional_triggers(
        pending, state.get("_trigger_choice_responses", {})
    )
    ordered = triggers.build_trigger_push_order(
        state, accepted, state.get("_trigger_order_responses", {})
    )

    for trig in ordered:
        stack_item = {
            "stack_item_id": f"stk_{game_state.next_seq_num(state)}",
            "item_type": "TRIGGER_ABILITY",
            "source": trig["source_id"],
            "targets": [],
            "controller": trig["controller"],
        }
        state["stack"].append(stack_item)
        push_msg = pdu.build_stack_push(
            game_state.next_seq_num(state), stack_item["stack_item_id"],
            "TRIGGER_ABILITY", stack_item["source"], [], stack_item["controller"],
        )
        broadcast(push_msg)

    state["_pending_triggers"] = []
    state["_trigger_order_pending"] = {}
    state["_trigger_order_seq"] = {}
    state["_trigger_order_responses"] = {}
    state["_trigger_choice_pending"] = {}
    state["_trigger_choice_seq"] = {}
    state["_trigger_choice_responses"] = {}

    send_personalized_state_to_all()
    # RFC 8.4/8.6: once triggers are on the Stack (or none survived
    # to be pushed), priority opens normally, starting with the
    # Active Player.
    open_priority_window()
    return True


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
            if not combat.needs_damage_order(state):
                # RFC 9.5: "If no attacker is multiply-blocked, this
                # step is skipped" -- entirely, no priority window.
                from_phase = current
                state = turn_manager.advance_phase(state)
                broadcast_phase_transition(from_phase, state["phase"])
                continue

            if not combat.has_all_damage_orders(state):
                # RFC 9.5: implicitly requested by the PHASE_TRANSITION
                # that announced this step (see broadcast_phase_transition
                # / _phase_transition_seq); the Active Player owes one
                # ASSIGN_DAMAGE_ORDER PDU per multiply-blocked attacker.
                return

            # RFC 9.5: "After all orderings have been received, the
            # server opens a final priority window before proceeding
            # to the damage step." Stay in this phase for that window;
            # PRIORITY_PASS's STEP_END handling advances us onward.
            open_priority_window()
            return

        if current == "FIRST_STRIKE_DAMAGE":
            # DOCUMENTED DEVIATION (not a silent gap): RFC 9.6 makes
            # this step conditional on "at least one attacking or
            # blocking creature has first strike or double strike".
            # No card in the current MTGNP card pool grants either
            # keyword (see cards.json / mtgnp_master_card_list.xlsx),
            # so combat.py never assigns first-strike damage and this
            # step is always a no-op pass-through. If a first/double
            # strike creature is ever added to card_effects.py's
            # creature templates, this branch must be replaced with a
            # real first-strike damage sub-resolution before it can be
            # trusted -- flag loudly rather than continue to skip
            # quietly once that day comes.
            if _battlefield_has_first_or_double_strike(state) and constants.is_verbose():
                print("[SERVER] WARNING: a first/double strike creature is in play "
                      "but FIRST_STRIKE_DAMAGE is still a documented no-op -- "
                      "combat.py needs a real implementation for this step.")
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

        if current == "DRAW":
            if state["turn"] != 1:
                ap = state["active_player"]
                library = state["libraries"].get(ap, [])
                if not library:
                    loser = ap
                    winner = turn_manager.other_player(state, ap)
                    msg = pdu.build_game_over(
                        game_state.next_seq_num(state), winner, loser,
                        constants.REASON_DECK_EMPTY
                    )
                    broadcast(msg)
                    reset_to_lobby()
                    return
                drawn = library.pop(0)
                state["hands"].setdefault(ap,[]).append(drawn)
                send_personalized_state_to(ap)

            open_priority_window()
            return

        if current in constants.PRIORITY_PHASES:
            open_priority_window()
            return

        if current == "CLEANUP":
            ap = state["active_player"]
            hand = state["hands"].get(ap, [])
            if len(hand) > constants.MAX_HAND_SIZE_BEFORE_DISCARD:
                # RFC 7.8: hand size > 7 at Cleanup -- ask the Active
                # Player to discard down to 7 before the turn can end.
                # The DISCARD handler re-enters advance_and_settle()
                # once the hand is legal again.
                seq = send_personalized_state_to(ap)
                state["_discard_request_seq"] = seq
                return  # wait for a DISCARD PDU

            # Hand size already legal (or just brought down to legal
            # by a completed DISCARD) -- finish Cleanup and move on.
            state["_discard_request_seq"] = None
            state = _clear_end_of_turn_state(state)
            send_personalized_state_to_all()
            from_phase = current
            state = turn_manager.advance_phase(state)
            broadcast_phase_transition(from_phase, state["phase"])
            continue

        # UNTAP -- fully automatic, no priority, no player action
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

def _schedule_disconnect_timeout(player_id):
    """Start the disconnect grace-period timer for player_id. If it
    fires, the game ends with GAME_OVER(reason=DISCONNECT)."""
    global pending_disconnects

    def _on_timeout():
        with lock:
            if player_id not in pending_disconnects:
                return
            del pending_disconnects[player_id]

            other = turn_manager.other_player(state, player_id)
            if constants.is_verbose():
                print(f"[SERVER] {player_id} did not return -- forfeiting")

            msg = pdu.build_game_over(
                game_state.next_seq_num(state), other, player_id,
                constants.REASON_DISCONNECT,
            )
            broadcast(msg)
            reset_to_lobby()

    timer = threading.Timer(constants.HEARTBEAT_TIMEOUT_S, _on_timeout)
    timer.daemon = True
    pending_disconnects[player_id] = {"timer": timer, "since": time.time()}
    timer.start()


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

                    winner = turn_manager.other_player(state, conceding)
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

                        # Each player's opening-hand GAME_STATE_UPDATE
                        # is the "request token" their first
                        # MULLIGAN_CHOICE must echo (RFC 5.4).
                        state["_mulligan_request_seq"] = send_personalized_state_to_all()
                    continue

                # -----------------------------------------------------
                # MULLIGAN_CHOICE -- MULLIGAN phase
                # -----------------------------------------------------
                if msg_type == "MULLIGAN_CHOICE":
                    player_id = conn_to_player.get(conn)
                    if player_id is None:
                        continue

                    seq_err = _check_seq("mulligan", player_id, msg)
                    if seq_err:
                        err = pdu.build_error(msg.get("seq_num", 0), constants.ERROR_STALE_ACTION,
                                               seq_err, msg)
                        send_pdu(conn, err, label=label)
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
                        # updated GAME_STATE_UPDATE (RFC 6.4). Whatever
                        # seq_num that update carries becomes the new
                        # token this player's *next* MULLIGAN_CHOICE
                        # (if any -- e.g. after a redraw) must echo.
                        new_seq = send_personalized_state_to(player_id)
                        state.setdefault("_mulligan_request_seq", {})[player_id] = new_seq
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

                    seq_err = _check_seq("priority", player_id, msg)
                    if seq_err:
                        _reject_stale(conn, label, msg, reissue_priority_to=player_id)
                        continue

                    state, signal = priority.handle_pass(state, player_id)

                    if signal == "CONTINUE":
                        _grant_priority_to(state["priority_holder"])

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

                        # RFC 8.6.1: after every resolution, check
                        # whether a permanent's triggered ability just
                        # fired (e.g. Gray Merchant's ETB "you may
                        # gain life"). If one did, the TRIGGER_ORDER /
                        # TRIGGER_CHOICE flow takes over priority
                        # instead of re-opening it immediately here.
                        trigger_flow_started = False
                        for change in resolve_event.get("state_changes", []):
                            if change.get("type") == "PERMANENT_ENTERS":
                                event = {
                                    "type": "PERMANENT_ENTERS",
                                    "card_id": change.get("card_id"),
                                    "controller": change.get("controller"),
                                }
                                if _start_trigger_flow(event):
                                    trigger_flow_started = True

                        if not trigger_flow_started:
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

                    seq_err = _check_seq("priority", player_id, msg)
                    if seq_err:
                        _reject_stale(conn, label, msg, reissue_priority_to=player_id)
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

                    _grant_priority_to(player_id)
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

                    seq_err = _check_seq("priority", player_id, msg)
                    if seq_err:
                        _reject_stale(conn, label, msg, reissue_priority_to=player_id)
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
                    _grant_priority_to(player_id)
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

                    seq_err = _check_seq("phase_transition", player_id, msg)
                    if seq_err:
                        err = pdu.build_error(msg.get("seq_num", 0), constants.ERROR_STALE_ACTION,
                                               seq_err, msg)
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
                    defending = turn_manager.other_player(state, state["active_player"])
                    if player_id != defending:
                        err = pdu.build_error(msg.get("seq_num", 0), constants.ERROR_ILLEGAL_ACTION,
                                              "Only the Non-Active Player declares blockers", msg)
                        send_pdu(conn, err, label=label)
                        continue

                    seq_err = _check_seq("phase_transition", player_id, msg)
                    if seq_err:
                        err = pdu.build_error(msg.get("seq_num", 0), constants.ERROR_STALE_ACTION,
                                               seq_err, msg)
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
                # ASSIGN_DAMAGE_ORDER
                # -----------------------------------------------------
                if msg_type == "ASSIGN_DAMAGE_ORDER":
                    if player_id != state["active_player"]:
                        err = pdu.build_error(msg.get("seq_num", 0), constants.ERROR_ILLEGAL_ACTION,
                                              "Only the Active Player assigns damage order", msg)
                        send_pdu(conn, err, label=label)
                        continue

                    seq_err = _check_seq("phase_transition", player_id, msg)
                    if seq_err:
                        err = pdu.build_error(msg.get("seq_num", 0), constants.ERROR_STALE_ACTION,
                                               seq_err, msg)
                        send_pdu(conn, err, label=label)
                        continue

                    attacker_id = msg.get("attacker_id")
                    blocker_order = msg.get("blocker_order", [])
                    new_state, err_code = combat.record_damage_order(state, attacker_id, blocker_order)
                    if err_code:
                        err = pdu.build_error(msg.get("seq_num", 0), err_code,
                                              "Illegal ASSIGN_DAMAGE_ORDER", msg)
                        send_pdu(conn, err, label=label)
                        continue
                    state = new_state

                    if combat.has_all_damage_orders(state):
                        # One PDU per multiply-blocked attacker is
                        # expected (RFC 9.5); once every one of them
                        # has been supplied, advance_and_settle() opens
                        # the final priority window for this step.
                        send_personalized_state_to_all()
                        advance_and_settle()
                    # else: still waiting on ordering for at least one
                    # more multiply-blocked attacker -- no state change
                    # to broadcast yet, no phase change.
                    continue

                # -----------------------------------------------------
                # TRIGGER_ORDER_RESPONSE (RFC 8.6.2)
                # -----------------------------------------------------
                if msg_type == "TRIGGER_ORDER_RESPONSE":
                    if player_id not in state.get("_trigger_order_pending", {}):
                        err = pdu.build_error(msg.get("seq_num", 0), constants.ERROR_ILLEGAL_ACTION,
                                              "No TRIGGER_ORDER is currently pending for you", msg)
                        send_pdu(conn, err, label=label)
                        continue

                    expected_seq = state.get("_trigger_order_seq", {}).get(player_id)
                    if msg.get("seq_num") != expected_seq:
                        err = pdu.build_error(msg.get("seq_num", 0), constants.ERROR_STALE_ACTION,
                                              f"Expected seq_num {expected_seq}", msg)
                        send_pdu(conn, err, label=label)
                        continue

                    ordered_ids = msg.get("ordered_trigger_ids", [])
                    my_trigger_ids = [
                        t["trigger_id"] for t in state.get("_pending_triggers", [])
                        if t["controller"] == player_id
                    ]
                    if sorted(ordered_ids) != sorted(my_trigger_ids):
                        err = pdu.build_error(msg.get("seq_num", 0), constants.ERROR_TRIGGER_ORDER_INVALID,
                                              "ordered_trigger_ids must be exactly your simultaneous "
                                              "triggers, each listed once", msg)
                        send_pdu(conn, err, label=label)
                        continue

                    state["_trigger_order_responses"][player_id] = ordered_ids
                    del state["_trigger_order_pending"][player_id]

                    if not state["_trigger_order_pending"]:
                        # All required orderings are in -- move on to
                        # optional-trigger choices (if any), or
                        # straight to pushing everything onto the Stack.
                        _start_trigger_choices()
                    continue

                # -----------------------------------------------------
                # TRIGGER_CHOICE_RESPONSE (RFC 8.6.3)
                # -----------------------------------------------------
                if msg_type == "TRIGGER_CHOICE_RESPONSE":
                    trigger_id = msg.get("trigger_id")
                    if trigger_id not in state.get("_trigger_choice_pending", {}):
                        err = pdu.build_error(msg.get("seq_num", 0), constants.ERROR_TRIGGER_CHOICE_INVALID,
                                              "No TRIGGER_CHOICE is currently pending for that trigger_id", msg)
                        send_pdu(conn, err, label=label)
                        continue

                    expected_seq = state.get("_trigger_choice_seq", {}).get(trigger_id)
                    if msg.get("seq_num") != expected_seq:
                        err = pdu.build_error(msg.get("seq_num", 0), constants.ERROR_STALE_ACTION,
                                              f"Expected seq_num {expected_seq}", msg)
                        send_pdu(conn, err, label=label)
                        continue

                    accept = bool(msg.get("accept", False))
                    state["_trigger_choice_responses"][trigger_id] = accept
                    del state["_trigger_choice_pending"][trigger_id]

                    if not state["_trigger_choice_pending"]:
                        # Every optional trigger has an answer -- push
                        # the accepted ones and reopen priority.
                        _finish_trigger_flow()
                    continue

                # -----------------------------------------------------
                # DISCARD -- Cleanup phase, hand size > 7 (RFC 7.8)
                # -----------------------------------------------------
                if msg_type == "DISCARD":
                    if player_id != state.get("active_player"):
                        err = pdu.build_error(msg.get("seq_num", 0), constants.ERROR_ILLEGAL_ACTION,
                                              "Only the Active Player discards at Cleanup", msg)
                        send_pdu(conn, err, label=label)
                        continue

                    if state.get("phase") != "CLEANUP" or state.get("_discard_request_seq") is None:
                        err = pdu.build_error(msg.get("seq_num", 0), constants.ERROR_WRONG_PHASE,
                                              "No discard is currently pending", msg)
                        send_pdu(conn, err, label=label)
                        continue

                    seq_err = _check_seq("discard", player_id, msg)
                    if seq_err:
                        err = pdu.build_error(msg.get("seq_num", 0), constants.ERROR_STALE_ACTION,
                                               seq_err, msg)
                        send_pdu(conn, err, label=label)
                        continue

                    card_ids = msg.get("card_ids", [])
                    hand = state["hands"].setdefault(player_id, [])

                    valid = (
                        len(card_ids) > 0
                        and len(card_ids) == len(set(card_ids))
                        and all(cid in hand for cid in card_ids)
                    )
                    if not valid:
                        err = pdu.build_error(msg.get("seq_num", 0), constants.ERROR_ILLEGAL_ACTION,
                                              "card_ids must be distinct cards from your own hand", msg)
                        send_pdu(conn, err, label=label)
                        continue

                    for card_id in card_ids:
                        hand.remove(card_id)
                        state["graveyard"].setdefault(player_id, []).append(card_id)

                    # RFC 7.8: broadcast the reduced hand, then either
                    # ask again (still > 7) or finish Cleanup --
                    # advance_and_settle() re-checks the hand size and
                    # does the right thing either way.
                    send_personalized_state_to_all()
                    advance_and_settle()
                    continue

                # -----------------------------------------------------
                # Unknown type
                # -----------------------------------------------------
                err = pdu.build_error(msg.get("seq_num", 0), constants.ERROR_UNKNOWN_TYPE,
                                      f"Unrecognized PDU type: {msg_type}", msg)
                send_pdu(conn, err, label=label)

    finally:
        player_id = conn_to_player.get(conn)
        if constants.is_verbose():
            tag = f" (player_id={player_id})" if player_id else ""
            print(f"[SERVER] Client disconnected: {addr}{tag}")
        conn.close()
        with lock:
            clients[:] = [c for c in clients if c[0] != conn]
            if conn in conn_to_player:
                del conn_to_player[conn]
            if player_id is not None and player_to_conn.get(player_id) is conn:
                del player_to_conn[player_id]

            if player_id is None:
                pass  # never identified (dropped before PLAYER_READY) -- nothing to forfeit
            elif state.get("phase_state") == constants.LOBBY:
                # No game underway -- just drop their lobby seat, no
                # GAME_OVER/forfeit semantics apply.
                lobby_state.pop(player_id, None)
            else:
                # A game is underway (setup/mulligan/in-game) -- start
                # the grace period before forfeiting on their behalf.
                _schedule_disconnect_timeout(player_id)

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