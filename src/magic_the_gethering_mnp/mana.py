COLORS = {"W", "U", "B", "R", "G"}

def _land_color(card_id: str, card_catalog:dict) -> str | None:
    ret = None

    if (card_id in card_catalog) and ((card_catalog.get(card_id))["card_type"] == "Land"):
        ret =  card_catalog.get(card_id)["color"]

    return ret

def _untapped_lands(state:dict, player_id: str, card_catalog: dict) -> dict[str, list[str]]:
    pass

def validate_and_pay(state: dict, player_id: str, mana_payment: dict, card_catalog: dict) -> tuple[bool, list[str]]:
    pass

def _find_permanent(state: dict, perm_i: str):
    pass