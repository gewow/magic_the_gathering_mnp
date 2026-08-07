import constants


def _empty_combat() -> dict:
    return {
        "attackers": [],
        "blockers": [],
        "damage_order": {},
    }


def _ensure_combat(state: dict) -> dict:
    if "_combat" not in state:
        state["_combat"] = _empty_combat()
    return state["_combat"]


def init_combat(state: dict) -> dict:
    state["_combat"] = _empty_combat()
    return state


def clear_combat(state: dict) -> dict:
    state["_combat"] = _empty_combat()
    return state


def has_attackers(state: dict) -> bool:
    combat = state.get("_combat", _empty_combat())
    return len(combat.get("attackers", [])) > 0


def _active_player(state: dict) -> str:
    return state["active_player"]


def _defending_player(state: dict) -> str:
    ap = _active_player(state)

    others = []
    all_players = list(state["life_totals"].keys())

    for p in all_players:
        if p!= ap:
            others.append(p)

    if len(others) != 1:
        raise ValueError(
            f"expected exactly one defending player, "
            f"found {others!r} among {all_players!r}"
        )
    
    # return "player_2" if ap == "player_1" else "player_1"
    return others[0]


def _find_permanent(state: dict, perm_id: str) -> tuple[str, dict] | None:
    for player_id, permanents in state["battlefield"].items():
        for perm in permanents:
            if perm["id"] == perm_id:
                return player_id, perm
    return None


def _is_creature(perm: dict) -> bool:
    return "power" in perm and "toughness" in perm


def _blockers_for_attacker(combat: dict, attacker_id: str) -> list[str]:
    return [
        b["creature_id"]
        for b in combat["blockers"]
        if b["blocking_id"] == attacker_id
    ]


def declare_attackers(state: dict, attackers: list[dict]) -> tuple[dict, str | None]:
    combat = _ensure_combat(state)
    defending = _defending_player(state)
    ap = _active_player(state)

    declared_ids: set[str] = set()
    for entry in attackers:
        creature_id = entry["creature_id"]
        target = entry["target"]

        if creature_id in declared_ids:
            return state, constants.ERROR_ILLEGAL_ACTION
        declared_ids.add(creature_id)

        found = _find_permanent(state, creature_id)
        if found is None:
            return state, constants.ERROR_ILLEGAL_ACTION

        owner, perm = found
        if owner != ap:
            return state, constants.ERROR_ILLEGAL_ACTION
        if not _is_creature(perm):
            return state, constants.ERROR_ILLEGAL_ACTION
        if perm.get("tapped", False):
            return state, constants.ERROR_ILLEGAL_ACTION
        if perm.get("summoning_sick", False):
            return state, constants.ERROR_ILLEGAL_ACTION
        if target != defending:
            return state, constants.ERROR_ILLEGAL_ACTION

    combat["attackers"] = list(attackers)
    combat["blockers"] = []
    combat["damage_order"] = {}

    for entry in attackers:
        _, perm = _find_permanent(state, entry["creature_id"])
        perm["tapped"] = True

    return state, None


def declare_blockers(state: dict, blockers: list[dict]) -> tuple[dict, str | None]:
    combat = _ensure_combat(state)
    nap = _defending_player(state)

    declared_attackers = {a["creature_id"] for a in combat["attackers"]}
    declared_blockers: set[str] = set()

    for entry in blockers:
        creature_id = entry["creature_id"]
        blocking_id = entry["blocking_id"]

        if creature_id in declared_blockers:
            return state, constants.ERROR_ILLEGAL_ACTION
        declared_blockers.add(creature_id)

        if blocking_id not in declared_attackers:
            return state, constants.ERROR_ILLEGAL_ACTION

        found = _find_permanent(state, creature_id)
        if found is None:
            return state, constants.ERROR_ILLEGAL_ACTION

        owner, perm = found
        if owner != nap:
            return state, constants.ERROR_ILLEGAL_ACTION
        if not _is_creature(perm):
            return state, constants.ERROR_ILLEGAL_ACTION
        if perm.get("tapped", False):
            return state, constants.ERROR_ILLEGAL_ACTION

    combat["blockers"] = list(blockers)
    return state, None


def needs_damage_order(state: dict) -> bool:
    combat = state.get("_combat", _empty_combat())
    for attacker in combat.get("attackers", []):
        attacker_id = attacker["creature_id"]
        if len(_blockers_for_attacker(combat, attacker_id)) >= 2:
            return True
    return False


def multiply_blocked_attacker_ids(state: dict) -> list[str]:
    """Every attacker_id that has 2+ blockers -- i.e. every attacker
    the Active Player owes an ASSIGN_DAMAGE_ORDER PDU for (RFC 9.5)."""
    combat = state.get("_combat", _empty_combat())
    return [
        a["creature_id"] for a in combat.get("attackers", [])
        if len(_blockers_for_attacker(combat, a["creature_id"])) >= 2
    ]


def has_all_damage_orders(state: dict) -> bool:
    """True once every multiply-blocked attacker has a recorded
    damage order. False (and thus "still waiting") when there's
    nothing to wait for, too -- callers should pair this with
    needs_damage_order() to distinguish "step is skipped" from "step
    is waiting"."""
    combat = state.get("_combat", _empty_combat())
    needed = multiply_blocked_attacker_ids(state)
    return all(aid in combat.get("damage_order", {}) for aid in needed)


def record_damage_order(state: dict, attacker_id: str, blocker_order: list[str]) -> tuple[dict, str | None]:
    """Validates and stores one ASSIGN_DAMAGE_ORDER PDU's ordering for
    a single multiply-blocked attacker. Multiple such PDUs may arrive
    in a row (one per multiply-blocked attacker); has_all_damage_orders()
    tells the caller when every one of them has been supplied."""
    combat = _ensure_combat(state)

    declared_attacker_ids = {a["creature_id"] for a in combat.get("attackers", [])}
    if attacker_id not in declared_attacker_ids:
        return state, constants.ERROR_ILLEGAL_ACTION

    blockers = set(_blockers_for_attacker(combat, attacker_id))
    if len(blockers) < 2:
        # Not actually a multiply-blocked attacker -- nothing to order.
        return state, constants.ERROR_ILLEGAL_ACTION

    if set(blocker_order) != blockers or len(blocker_order) != len(blockers):
        return state, constants.ERROR_ILLEGAL_ACTION

    combat["damage_order"][attacker_id] = list(blocker_order)
    return state, None


def _apply_damage_to_creature(state: dict, creature_id: str, amount: int) -> None:
    found = _find_permanent(state, creature_id)
    if found is None:
        return
    _, perm = found
    perm["damage"] = perm.get("damage", 0) + amount


def resolve_combat_damage(
    state: dict,
    damage_order: dict[str, list[str]] | None = None,
) -> tuple[dict, list[dict], list[str]]:
    combat = _ensure_combat(state)
    if damage_order:
        combat["damage_order"].update(damage_order)

    defending = _defending_player(state)
    damage_events: list[dict] = []

    for attacker_entry in combat["attackers"]:
        attacker_id = attacker_entry["creature_id"]
        found = _find_permanent(state, attacker_id)
        if found is None:
            continue
        _, attacker_perm = found
        power = attacker_perm.get("power", 0)

        blocker_ids = _blockers_for_attacker(combat, attacker_id)
        if not blocker_ids:
            damage_events.append({
                "source": attacker_id,
                "target": defending,
                "amount": power,
            })
            state["life_totals"][defending] -= power
            continue

        if len(blocker_ids) == 1:
            damage_events.append({
                "source": attacker_id,
                "target": blocker_ids[0],
                "amount": power,
            })
        else:
            order = combat["damage_order"].get(attacker_id, blocker_ids)
            ordered_blockers = [bid for bid in order if bid in blocker_ids]
            for bid in blocker_ids:
                if bid not in ordered_blockers:
                    ordered_blockers.append(bid)

            remaining = power
            for blocker_id in ordered_blockers:
                if remaining <= 0:
                    break
                blocker_found = _find_permanent(state, blocker_id)
                if blocker_found is None:
                    continue
                _, blocker_perm = blocker_found
                lethal = max(blocker_perm.get("toughness", 0) - blocker_perm.get("damage", 0), 0)
                assigned = min(remaining, lethal) if lethal > 0 else remaining
                if assigned <= 0 and remaining > 0:
                    assigned = remaining
                if assigned > 0:
                    damage_events.append({
                        "source": attacker_id,
                        "target": blocker_id,
                        "amount": assigned,
                    })
                    remaining -= assigned

    for blocker_entry in combat["blockers"]:
        blocker_id = blocker_entry["creature_id"]
        attacker_id = blocker_entry["blocking_id"]
        blocker_found = _find_permanent(state, blocker_id)
        attacker_found = _find_permanent(state, attacker_id)
        if blocker_found is None or attacker_found is None:
            continue
        _, blocker_perm = blocker_found
        power = blocker_perm.get("power", 0)
        if power > 0:
            damage_events.append({
                "source": blocker_id,
                "target": attacker_id,
                "amount": power,
            })

    for event in damage_events:
        target = event["target"]
        amount = event["amount"]
        if target in state["life_totals"]:
            continue
        _apply_damage_to_creature(state, target, amount)

    creatures_died: list[str] = []
    for player_id, permanents in state["battlefield"].items():
        for perm in permanents:
            if "toughness" not in perm:
                continue
            if perm.get("damage", 0) >= perm["toughness"]:
                creatures_died.append(perm["id"])

    return state, damage_events, creatures_died