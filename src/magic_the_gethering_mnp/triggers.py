#check every permanent on the battlefield for triggered abilities that respond to 'event'
def detect_triggers(state: dict, event: dict, trigger_catalog: dict = None) -> list[dict]:
    if trigger_catalog is None:
        return []

    pending = []
    for controller, permanents in state["battlefield"].items():
        for permanent in permanents:
            defs = trigger_catalog.get(permanent["id"], [])
            for i, trigger_def in enumerate(defs):
                if trigger_def["condition_fn"](event, permanent, state):
                    pending.append({
                        "trigger_id": f"trg_{permanent['id']}_{event.get('type', '?')}_{i}",
                        "source_id": permanent["id"],
                        "controller": controller,
                        "optional": trigger_def.get("optional", False),
                        "requires_target": trigger_def.get("requires_target", False),
                        "effect_summary": trigger_def.get("effect_summary", "")
                    })

    return pending

#optional triggers only pass through if optional_responses[trigger_id] is trie
#decclined optional trigger is silently dropped, no STACK_PUSH
def filter_accepted_optional_triggers(pending_triggers: list[dict], optional_responses: dict) -> list[dict]:
    result = []
    for trigger in pending_triggers:
        if not trigger.get("optional", False):
            result.append(trigger)
            continue

        trigger_id = trigger["trigger_id"]
        if trigger_id not in optional_responses:
            raise ValueError(
                f"Missing TRIGGER_CHOICE_RESPONSE for optional trigger {trigger_id}"
            )

        if optional_responses[trigger_id]:
            result.append(trigger)

    return result

def build_trigger_push_order(state: dict, pending_triggers: list[dict], ordering_responses: dict = None) -> list[dict]:
    ap = state["active_player"]
    nap = "player_2" if ap == "player_1" else "player_1"

    by_controller = {ap: [], nap: []}
    for trig in pending_triggers:
        by_controller.setdefault(trig["controller"], []).append(trig)

    result = []
    for player_id in (ap, nap):
        triggers_for_player = by_controller.get(player_id, [])
        if len(triggers_for_player) == 0:
            continue
        elif len(triggers_for_player) == 1:
            result.append(triggers_for_player[0])
        else:
            fired_ids = [t["trigger_id"] for t in triggers_for_player]
            if ordering_responses is None or player_id not in ordering_responses:
                raise ValueError(
                    f"{player_id} controls {len(triggers_for_player)} simultaneous"
                    f"triggers {fired_ids} and must supply an order via"
                    f"TRIGGER_ORDER_RESPONSE before these can be placed on the stack"
                )

            order = ordering_responses[player_id]
            if sorted(order) != sorted(fired_ids):
                raise ValueError(
                    f"Ordering response for {player_id} must contain exavtly"
                    f"{fired_ids}, got {order}"
                )
            by_id = {t["trigger_id"]: t for t in triggers_for_player}
            result.extend(by_id[tid] for tid in order)

    return result


