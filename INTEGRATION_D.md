# Task D Integration Notes (Member C + B)

This document defines the handoff contracts between Member D's combat/card-effect
code and Member C's turn engine. Share with the group before wiring the server loop.

## Card effect dispatch (Member C → Member D)

Wire stack resolution like this:

```python
from card_effects import apply_card_effect

result = priority.process_stack_and_sbas(state, apply_effect_fn=apply_card_effect)
```

`apply_card_effect(state, stack_item) -> tuple[dict, list[dict]]` keys off the
base card id (`lightning_bolt_003` → `lightning_bolt`). Unknown cards resolve as no-op.

Implemented effects: Lightning Bolt, Shock, Counterspell, Goblin Guide, Gray Merchant.

## Combat helpers (Member C → Member D)

Import from `combat.py`:

| Function | When to call |
|----------|--------------|
| `init_combat(state)` | At `BEGIN_COMBAT` (optional; `declare_attackers` auto-inits) |
| `declare_attackers(state, attackers)` | On `DECLARE_ATTACKERS` PDU from AP |
| `declare_blockers(state, blockers)` | On `DECLARE_BLOCKERS` PDU from NAP |
| `needs_damage_order(state)` | After blockers declared; skip `ASSIGN_DAMAGE_ORDER` if `False` |
| `resolve_combat_damage(state, damage_order=None)` | At `COMBAT_DAMAGE` step |
| `has_attackers(state)` | After declare attackers; if `False`, skip to `END_OF_COMBAT` |
| `clear_combat(state)` | At `END_OF_COMBAT` after priority window closes |

## Combat phase flow

```
BEGIN_COMBAT → (priority, both pass)
DECLARE_ATTACKERS → AP sends PDU (echo PHASE_TRANSITION seq_num)
  → if empty attackers: jump to END_OF_COMBAT (skip blockers/damage)
  → else: priority window, then DECLARE_BLOCKERS
DECLARE_BLOCKERS → NAP sends PDU
  → if needs_damage_order(): ASSIGN_DAMAGE_ORDER (one PDU per multi-blocked attacker)
  → skip FIRST_STRIKE_DAMAGE in MTGNP 1.0 (no first strike cards)
COMBAT_DAMAGE → resolve_combat_damage() → broadcast COMBAT_DAMAGE_RESULT
  → run_sba_until_stable() → GAME_STATE_UPDATE
END_OF_COMBAT → clear_combat() → priority → POSTCOMBAT_MAIN
```

## COMBAT_DAMAGE_RESULT → SBA

After `resolve_combat_damage`:

1. Broadcast `pdu.build_combat_damage_result(seq, damage_events, life_totals, creatures_died)`
2. Apply SBA via `sba.run_sba_until_stable(state)` (moves lethal creatures, checks life)
3. Broadcast personalized `GAME_STATE_UPDATE` to each player

Life totals are already updated inside `resolve_combat_damage` for unblocked player damage.

## seq_num echo rules for combat PDUs

Per RFC 5.4, `DECLARE_ATTACKERS`, `DECLARE_BLOCKERS`, and `ASSIGN_DAMAGE_ORDER`
must echo the **PHASE_TRANSITION** seq_num that signaled that step — not the
last `PRIORITY_GRANT`.

## Team blockers to resolve

| Owner | Issue |
|-------|-------|
| **Member B** | `cards.json` is empty — lobby deck validation and mana costs need card catalog entries |
| **Member C** | `constants.PHASE_ORDER` missing comma between `FIRST_STRIKE_DAMAGE` and `COMBAT_DAMAGE`; also omits `BEGIN_COMBAT` / `END_OF_COMBAT` from RFC 10.2.4 |
| **Member A** | `pdu.buld_declare_blockers` typo — clients call the existing name until renamed |
