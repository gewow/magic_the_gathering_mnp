import json, re
import openpyxl

wb = openpyxl.load_workbook('mtgnp_master_card_list.xlsx')

# --- Master Card List: base card definitions ---
ws_master = wb['Master Card List']
master_rows = list(ws_master.iter_rows(min_row=3, values_only=True))

base_cards = {}
for row in master_rows:
    (base_id, name, ctype, subtype, color, cmc, w, u, b, r, g, generic,
     power, toughness, copies, effect) = row

    mana_cost = {}
    for sym, val in (("W", w), ("U", u), ("B", b), ("R", r), ("G", g), ("generic", generic)):
        if val:
            mana_cost[sym] = int(val)

    def norm_pt(v):
        if v in ("-", None):
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return v

    base_cards[base_id] = {
        "base_id": base_id,
        "name": name,
        "card_type": ctype,
        "subtype": subtype,
        "color": color,
        "cmc": int(cmc) if cmc is not None else 0,
        "mana_cost": mana_cost,
        "power": norm_pt(power),
        "toughness": norm_pt(toughness),
        "copies_in_set": int(copies) if copies is not None else None,
        "effect": effect,
    }

# --- Card Instances: individual protocol card_id values ---
ws_inst = wb['Card Instances']
inst_rows = list(ws_inst.iter_rows(min_row=3, values_only=True))

cards = {}
for row in inst_rows:
    card_id, name, ctype, color, copy_num = row
    base_id = re.sub(r'_\d+$', '', card_id)
    base = base_cards.get(base_id)
    if base is None:
        continue
    entry = dict(base)
    entry["card_id"] = card_id
    entry["copy_number"] = int(copy_num) if copy_num is not None else None
    del entry["copies_in_set"]
    cards[card_id] = entry

with open('cards.json', 'w') as f:
    json.dump(cards, f, indent=2, sort_keys=True)