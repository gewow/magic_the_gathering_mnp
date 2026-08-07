COLORS = {"W", "U", "B", "R", "G"}

def _land_color(card_id: str, card_catalog:dict) -> str | None:
    ret = None

    if (card_id in card_catalog) and ((card_catalog.get(card_id))["card_type"] == "Land"):
        ret =  (card_catalog.get(card_id) or {}).get("color")

    return ret

def _untapped_lands(state:dict, player_id: str, card_catalog: dict) -> dict[str, list[str]]:
    by_color = {}

    for color in COLORS:
        by_color[color] = []

    permanents = state["battlefield"].get(player_id, [])

    for perm in permanents:
        if perm["tapped"] != True:
            color = _land_color(perm["id"], card_catalog)
            if color == None:
                continue
            by_color[color].append(perm["id"])

    return by_color

def _payment_matches_cost(mana_payment: dict, mana_cost:dict) -> bool:
    cost = dict(mana_cost or {})
    payment = dict(mana_payment or {})

    for key in COLORS | {"generic"}:
        if payment.get(key,0) != cost.get(key,0):
            return False
    return True


def validate_and_pay(state: dict, player_id: str, mana_payment: dict, card_catalog: dict, card_id: str | None = None) -> tuple[bool, list[str]]:
    mana_pay = dict(mana_payment or {})
    bFlag = True
    ret = (False, [])
    used_lands = []
    remaining_lands = []

    if card_id is not None:
        card = card_catalog.get(card_id, {})
        mana_cost = card.get("mana_cost", {})
        if not _payment_matches_cost(mana_payment, mana_cost):
            return (False, [])

    generic = mana_pay.pop("generic", 0)


    for mana_col in mana_pay:
        if (mana_col not in COLORS):
            bFlag = False
            break

    if bFlag:
        group_untapped = _untapped_lands(state, player_id, card_catalog)

        for color, amount in mana_pay.items():
            if len(group_untapped[color]) >= amount:
                for i in range(amount):
                    used_lands.append(group_untapped[color].pop())
            else:
                return (False, [])

        for color in group_untapped:
            remaining_lands.extend(group_untapped[color])

        if len(remaining_lands) >= generic:
            used_lands.extend(remaining_lands[:generic])

            ret = (True, used_lands)

            for card_id in used_lands:
                garb, perm = _find_permanent(state, card_id)
                perm["tapped"] = True
                
    return ret


def _find_permanent(state: dict, perm_id: str):
    p_battlefield = list(state["battlefield"].keys())
    bFlag = False
    ret = (None, None)

    for p in p_battlefield:
        for perm in state["battlefield"][p]:
            if (perm["id"] == perm_id):
                ret = (p, perm)
                bFlag = True
                break
        if bFlag:
            break

    return ret