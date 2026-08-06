"""Card effect implementations and dispatch for stack resolution."""

from typing import Callable


def card_base_id(card_id: str) -> str:
    """Map instance id like lightning_bolt_003 to base effect key lightning_bolt."""
    if "_" in card_id and card_id.rsplit("_", 1)[-1].isdigit():
        return card_id.rsplit("_", 1)[0]
    return card_id


def _find_permanent(state: dict, perm_id: str) -> tuple[str, dict] | None:
    for player_id, permanents in state["battlefield"].items():
        for perm in permanents:
            if perm["id"] == perm_id:
                return player_id, perm
    return None


def _apply_damage(state: dict, target: str, amount: int) -> dict:
    if target in state["life_totals"]:
        state["life_totals"][target] -= amount
        return {"type": "DAMAGE", "target": target, "amount": amount}

    found = _find_permanent(state, target)
    if found is None:
        return {"type": "DAMAGE", "target": target, "amount": amount}

    _, perm = found
    perm["damage"] = perm.get("damage", 0) + amount
    return {"type": "DAMAGE", "target": target, "amount": amount}


def _remove_from_hand(state: dict, player_id: str, card_id: str) -> None:
    hand = state["hands"][player_id]
    if card_id in hand:
        hand.remove(card_id)


def _creature_template(card_id: str) -> dict:
    base = card_base_id(card_id)
    templates = {
        "goblin_guide": {
            "power": 2,
            "toughness": 2,
        },
        "gray_merchant": {
            "power": 2,
            "toughness": 4,
        },
    }
    stats = templates.get(base, {"power": 1, "toughness": 1})
    return {
        "id": card_id,
        "tapped": False,
        "damage": 0,
        "power": stats["power"],
        "toughness": stats["toughness"],
        "summoning_sick": True,
    }


def _count_black_devotion(state: dict, controller: str) -> int:
    count = 0
    for perm in state["battlefield"].get(controller, []):
        base = card_base_id(perm["id"])
        if base == "swamp" or base == "gray_merchant":
            count += 1
    return count


def effect_lightning_bolt(state: dict, stack_item: dict) -> tuple[dict, list[dict]]:
    targets = stack_item.get("targets", [])
    if not targets:
        return state, []

    target = targets[0]
    change = _apply_damage(state, target, 3)
    controller = stack_item.get("controller", stack_item.get("controller_id"))
    if controller and stack_item.get("source"):
        _remove_from_hand(state, controller, stack_item["source"])

    return state, [change]


def effect_shock(state: dict, stack_item: dict) -> tuple[dict, list[dict]]:
    targets = stack_item.get("targets", [])
    if not targets:
        return state, []

    target = targets[0]
    change = _apply_damage(state, target, 2)
    controller = stack_item.get("controller", stack_item.get("controller_id"))
    if controller and stack_item.get("source"):
        _remove_from_hand(state, controller, stack_item["source"])

    return state, [change]


def effect_counterspell(state: dict, stack_item: dict) -> tuple[dict, list[dict]]:
    targets = stack_item.get("targets", [])
    if not targets:
        return state, []

    target_id = targets[0]
    countered = None
    for item in state["stack"]:
        if item.get("stack_item_id") == target_id:
            countered = item
            break

    if countered is not None:
        state["stack"] = [
            item for item in state["stack"]
            if item.get("stack_item_id") != target_id
        ]

    controller = stack_item.get("controller", stack_item.get("controller_id"))
    if controller and stack_item.get("source"):
        _remove_from_hand(state, controller, stack_item["source"])

    return state, [{"type": "COUNTER", "target": target_id}]


def effect_goblin_guide(state: dict, stack_item: dict) -> tuple[dict, list[dict]]:
    card_id = stack_item.get("source")
    controller = stack_item.get("controller", stack_item.get("controller_id"))
    if not card_id or not controller:
        return state, []

    _remove_from_hand(state, controller, card_id)
    permanent = _creature_template(card_id)
    state["battlefield"][controller].append(permanent)

    return state, [{
        "type": "PERMANENT_ENTERS",
        "card_id": card_id,
        "controller": controller,
        "tapped": False,
    }]


def effect_gray_merchant(state: dict, stack_item: dict) -> tuple[dict, list[dict]]:
    card_id = stack_item.get("source")
    controller = stack_item.get("controller", stack_item.get("controller_id"))
    if not card_id or not controller:
        return state, []

    _remove_from_hand(state, controller, card_id)
    permanent = _creature_template(card_id)
    state["battlefield"][controller].append(permanent)

    changes: list[dict] = [{
        "type": "PERMANENT_ENTERS",
        "card_id": card_id,
        "controller": controller,
        "tapped": False,
    }]

    devotion = _count_black_devotion(state, controller)
    if devotion > 0:
        for player_id in state["life_totals"]:
            if player_id == controller:
                state["life_totals"][player_id] += devotion
                changes.append({
                    "type": "LIFE_GAIN",
                    "target": player_id,
                    "amount": devotion,
                })
            else:
                state["life_totals"][player_id] -= devotion
                changes.append({
                    "type": "DAMAGE",
                    "target": player_id,
                    "amount": devotion,
                })

    return state, changes


EFFECTS: dict[str, Callable[[dict, dict], tuple[dict, list[dict]]]] = {
    "lightning_bolt": effect_lightning_bolt,
    "shock": effect_shock,
    "counterspell": effect_counterspell,
    "goblin_guide": effect_goblin_guide,
    "gray_merchant": effect_gray_merchant,
}


def apply_card_effect(state: dict, stack_item: dict) -> tuple[dict, list[dict]]:
    source = stack_item.get("source", "")
    base = card_base_id(source)
    fn = EFFECTS.get(base)
    if fn is None:
        return state, []
    return fn(state, stack_item)
