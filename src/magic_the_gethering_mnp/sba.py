def check_state_based_actions(state):
    events = []

    # when life <= 0 
    # the Active Player loses and the Non-Active Player wins. This must
    # produce exactly ONE event, never one contradictory event per player.
    players_at_zero = [p for p, life in state["life_totals"].items() if life <= 0]
    if players_at_zero:
        if len(players_at_zero) >= 2:
            loser = state["active_player"]
        else:
            loser = players_at_zero[0]
        winner = next(p for p in state["life_totals"] if p != loser)
        events.append({
            "type": "LIFE_ZERO",
            "loser": loser,
            "winner": winner,
        })

    # lethal damage on creatures.
    for player_id, permanents in state["battlefield"].items():
        for perm in permanents:
            if "toughness" not in perm:
                continue  # non-creature permanent (e.g. a land)
            damage = perm.get("damage", 0)
            toughness = perm["toughness"]
            # if toughness > 0 and damage >= toughness:
            #     events.append({
            #         "type": "CREATURE_DIED",
            #         "card_id": perm["id"],
            #         "controller": player_id,
            #         "reason": "LETHAL_DAMAGE",
            #     })
            if toughness <= 0:
                events.append({
                    "type": "CREATURE_DIED",
                    "card_id": perm["id"],
                    "controller": player_id,
                    "reason": "ZERO_TOUGHNESS",
                })
            elif damage >= toughness:
                events.append({
                    "type": "CREATURE_DIED",
                    "card_id": perm["id"],
                    "controller": player_id,
                    "reason": "LETHAL_DAMAGE",
                })

    return events

def apply_sba_events(state, events):
    for event in events:
        if event["type"] == "CREATURE_DIED":
            controller = event["controller"]
            card_id = event["card_id"]
            battlefield = state["battlefield"][controller]
            perm = next((p for p in battlefield if p["id"] == card_id), None)
            if perm:
                battlefield.remove(perm)
                state["graveyard"][controller].append(card_id)
    return state

def run_sba_until_stable(state, max_iterations=100):
    all_events = []
    for _ in range(max_iterations):
        events = check_state_based_actions(state)
        if not events:
            return state, all_events, None

        all_events.extend(events)

        life_zero = next((e for e in events if e["type"] == "LIFE_ZERO"), None)
        if life_zero:
            return state, all_events, life_zero

        state = apply_sba_events(state, events)

    raise RuntimeError(
        "run_sba_until_stable did not stabilize after"
        f"{max_iterations} iterations. Likely an SBA cycle bug"
    )