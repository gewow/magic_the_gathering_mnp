import constants

def validate_basic(pdu: dict) -> tuple[bool, str | None]:
    if not isinstance(pdu, dict):
        return False, "PDU is not a JSON object"
    if "type" not in pdu:
        return False, "Missing required field: type"
    if "seq_num" not in pdu:
        return False, "Missing required field: seq_num"
    if pdu["type"] not in constants.PDU_TYPES:
        return False, f"Unknown type: {pdu['type']}"
    if not isinstance(pdu["seq_num"], int):
        return False, "seq_num must be an integer"
    return True, None

def requires_priority_echo(pdu_type: str) -> bool:
    return pdu_type in constants.PRIORITY_ECHO_TYPES

#SERVER BUILDERS

def build_player_ready(seq_num: int, player_id: str, deck_list: list[str]) -> dict:
    return {
        "type": "PLAYER_READY",
        "seq_num": seq_num,
        "player_id": player_id,
        "deck_list": deck_list,
    }

def build_mulligan_choice(seq_num: int, keep: bool, cards_to_bottom: list[str]) -> dict:
    return {
        "type": "MULLIGAN_CHOICE",
        "seq_num": seq_num, 
        "keep": keep,
        "cards_to_bottom": cards_to_bottom,
    }

def build_priority_pass(seq_num: int) -> dict:
    return {"type": "PRIORITY_PASS", "seq_num": seq_num}

def build_cast_spell(seq_num: int, card_id: str, targets: list[str],
                      mana_payment: dict) -> dict:
    return {
        "type": "CAST_SPELL",
        "seq_num": seq_num,
        "card_id": card_id,
        "targets": targets,
        "mana_payment": mana_payment,
    }

def build_activate_ability(seq_num: int, source_id: str, ability_index:int, targets: list[str], cost_payment: dict) -> dict:
    return {
        "type": "ACTIVATE_ABILITY",
        "seq_num": seq_num,
        "source_id": source_id,
        "ability_index": ability_index,
        "targets": targets,
        "cost_payment": cost_payment,
    }

def build_declare_attackers(seq_num: int, attackers: list[dict]) -> dict:
    return {"type": "DECLARE_ATTACKERS", "seq_num": seq_num, "attackers": attackers}

def buld_declare_blockers(seq_num: int, blockers: list[dict]) -> dict:
    return {"type": "DECLARE_BLOCKERS", "seq_num": seq_num, "blockers": blockers}

def build_assign_damage_order(seq_num: int, attacker_id: str, blocker_order: list[str]) -> dict:
    return{
        "type": "ASSIGN_DAMAGE_ORDER",
        "seq_num": seq_num,
        "attacker_id": attacker_id,
        "blocker_order": blocker_order,
    }

def build_play_land(seq_num: int, card_id: str) -> dict:
    return {"type": "PLAY_LAND", "seq_num": seq_num, "card_id": card_id}

def build_discard(seq_num: int, card_ids: list[str]) -> dict:
    return {"type": "DISCARD", "seq_num": seq_num, "card_ids": card_ids}

def build_concede(seq_num: int, player_id: str) -> dict:
    return {"type": "CONCEDE", "seq_num": seq_num, "player_id": player_id}

def build_trigger_order_response(seq_num: int, ordered_trigger_ids: list[str]) -> dict:
    return {
        "type": "TRIGGER_ORDER_RESPONSE",
        "seq_num": seq_num,
        "ordered_trigger_ids": ordered_trigger_ids,
    }


def build_trigger_choice_response(seq_num: int, trigger_id: str, accept: bool,
                                   chosen_target: str | None = None) -> dict:
    return {
        "type": "TRIGGER_CHOICE_RESPONSE",
        "seq_num": seq_num,
        "trigger_id": trigger_id,
        "accept": accept,
        "chosen_target": chosen_target,
    }


def build_ping(seq_num: int, timestamp: int) -> dict:
    return {"type": "PING", "seq_num": seq_num, "timestamp": timestamp}

#CLIENT BUILDERS

def build_game_state_update(seq_num: int, state: dict) -> dict:
    return {"type": "GAME_STATE_UPDATE", "seq_num": seq_num, "state": state}

def build_phase_transition(seq_num: int, from_phase: str, to_phase: str, active_player: str, turn: int) -> dict:
    return {
        "type": "PHASE_TRANSITION",
        "seq_num": seq_num,
        "from_phase": from_phase,
        "to_phase": to_phase,
        "active_player": active_player,
        "turn": turn,
    }

def build_priority_grant(seq_num: int, player_id: str, time_limit_ms: int = constants.DEFAULT_TIME_LIMIT_MS) -> dict:
    return {
        "type": "PRIORITY_GRANT",
        "player_id": player_id,
        "seq_num": seq_num,
        "time_limit_ms": time_limit_ms,
    }

def build_stack_push(seq_num: int, stack_item_id: str, item_type: str, source: str, targets: list[str], controller: str) -> dict:
    return {
            "type": "STACK_PUSH",
            "seq_num": seq_num,
            "stack_item_id": stack_item_id,
            "item_type": item_type,  # SPELL | ABILITY | TRIGGER_ABILITY
            "source": source,
            "targets": targets,
            "controller": controller,
    }

def build_stack_resolve(seq_num: int, stack_item_id: str, result: str,
                         state_changes: list[dict]) -> dict:
    return {
        "type": "STACK_RESOLVE",
        "seq_num": seq_num,
        "stack_item_id": stack_item_id,
        "result": result,  # RESOLVED | FIZZLE
        "state_changes": state_changes,
    }


def build_trigger_order(seq_num: int, player_id: str, trigger_ids: list[str]) -> dict:
    return {
        "type": "TRIGGER_ORDER",
        "seq_num": seq_num,
        "player_id": player_id,
        "trigger_ids": trigger_ids,
    }


def build_trigger_choice(seq_num: int, trigger_id: str, source_id: str,
                          effect_summary: str, requires_target: bool,
                          legal_targets: list[str]) -> dict:
    return {
        "type": "TRIGGER_CHOICE",
        "seq_num": seq_num,
        "trigger_id": trigger_id,
        "source_id": source_id,
        "effect_summary": effect_summary,
        "requires_target": requires_target,
        "legal_targets": legal_targets,
    }


def build_combat_damage_result(seq_num: int, damage_events: list[dict],
                                life_totals: dict, creatures_died: list[str]) -> dict:
    return {
        "type": "COMBAT_DAMAGE_RESULT",
        "seq_num": seq_num,
        "damage_events": damage_events,
        "life_totals": life_totals,
        "creatures_died": creatures_died,
    }


def build_game_over(seq_num: int, winner_id: str, loser_id: str, reason: str) -> dict:
    assert reason in {
        constants.REASON_LIFE_ZERO, constants.REASON_DECK_EMPTY,
        constants.REASON_CONCEDE, constants.REASON_DISCONNECT,
    }, f"Invalid GAME_OVER reason: {reason}"
    return {
        "type": "GAME_OVER",
        "seq_num": seq_num,
        "winner_id": winner_id,
        "loser_id": loser_id,
        "reason": reason,
    }


def build_error(seq_num: int, code: str, message: str,
                 rejected_action: dict | None = None) -> dict:
    assert code in constants.ALL_ERROR_CODES, f"Unknown error code: {code}"
    return {
        "type": "ERROR",
        "seq_num": seq_num,
        "code": code,
        "message": message,
        "rejected_action": rejected_action,
    }


def build_pong(seq_num: int, timestamp: int) -> dict:
    return {"type": "PONG", "seq_num": seq_num, "timestamp": timestamp}