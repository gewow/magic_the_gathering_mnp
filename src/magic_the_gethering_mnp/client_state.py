"""MTGNP thin client — sends actions, renders authoritative server state."""

from __future__ import annotations

import socket
import threading
import time

import constants
import framing
import pdu


COMBAT_PHASES = {
    "DECLARE_ATTACKERS",
    "DECLARE_BLOCKERS",
    "ASSIGN_DAMAGE_ORDER",
}


class MTGNPClient:
    """TCP client for one MTGNP player session."""

    def __init__(
        self,
        host: str,
        port: int,
        player_id: str,
        deck_list: list[str],
        verbose: bool = False,
    ) -> None:
        self.host = host
        self.port = port
        self.player_id = player_id
        self.deck_list = deck_list
        self.verbose = verbose

        self.sock: socket.socket | None = None
        self.state: dict | None = None
        self.running = False

        self.client_seq = 0
        self.action_token: int | None = None
        self.last_server_seq: int | None = None
        self.ping_seq = 0

        self.current_phase: str | None = None
        self.holds_priority = False
        self.pending_trigger_order: dict | None = None
        self.pending_trigger_choice: dict | None = None
        self.pending_discard = False
        self.mulligan_submitted = False

        self._heartbeat_thread: threading.Thread | None = None
        self._heartbeat_stop = threading.Event()
        self._pong_event = threading.Event()
        self._pong_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> None:
        self.sock = socket.create_connection((self.host, self.port))
        self.running = True
        self._start_heartbeat()

    def disconnect(self) -> None:
        self.running = False
        self._heartbeat_stop.set()
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def _next_client_seq(self) -> int:
        self.client_seq += 1
        return self.client_seq

    def _send(self, built_pdu: dict) -> None:
        if self.sock is None:
            raise framing.ConnectionClosed("Not connected")
        framing.send_pdu(self.sock, built_pdu, label=self.player_id)

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def replace_state(self, new_state: dict) -> None:
        """Wholesale overwrite — never patch (RFC 4.3)."""
        self.state = dict(new_state)
        phase = self.state.get("phase")
        if phase:
            self.current_phase = phase
        if phase == "MULLIGAN":
            self.pending_discard = False
        hand = self.state.get("hand", [])
        if self.current_phase == "CLEANUP" and len(hand) > constants.MAX_HAND_SIZE_BEFORE_DISCARD:
            self.pending_discard = True

    def render(self) -> None:
        print("\n" + "=" * 60)
        print(f"Player: {self.player_id}")
        if self.state is None:
            print("(no state yet)")
            print("=" * 60)
            return

        phase = self.state.get("phase", "?")
        print(f"Phase: {phase}  Turn: {self.state.get('turn', '?')}  "
              f"Active: {self.state.get('active_player', '?')}")
        print(f"Priority: {self.state.get('priority_holder', 'none')}")
        print(f"Life: {self.state.get('life_totals', {})}")

        hand = self.state.get("hand")
        if hand is not None:
            print(f"Your hand ({len(hand)}): {hand}")
        hand_counts = self.state.get("hand_counts", {})
        if hand_counts:
            print(f"Opponent hand counts: {hand_counts}")

        print(f"Library counts: {self.state.get('library_counts', {})}")
        print(f"Land played this turn: {self.state.get('land_played_this_turn', False)}")

        battlefield = self.state.get("battlefield", {})
        for owner, permanents in battlefield.items():
            print(f"Battlefield [{owner}]: {permanents}")

        graveyard = self.state.get("graveyard", {})
        for owner, cards in graveyard.items():
            if cards:
                print(f"Graveyard [{owner}]: {cards}")

        stack = self.state.get("stack", [])
        if stack:
            print(f"Stack ({len(stack)}): {stack}")

        if self.state.get("phase") == constants.LOBBY:
            print(f"Players ready: {self.state.get('players_ready', 0)}")
            print(f"Waiting for: {self.state.get('waiting_for', [])}")

        print("=" * 60 + "\n")

    # ------------------------------------------------------------------
    # Heartbeat (RFC 4.3 — PING every 30s, disconnect if no PONG in 10s)
    # ------------------------------------------------------------------

    def _start_heartbeat(self) -> None:
        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name=f"heartbeat-{self.player_id}",
        )
        self._heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        while not self._heartbeat_stop.wait(constants.HEARTBEAT_INTERVAL_S):
            if not self.running or self.sock is None:
                break
            try:
                self.ping_seq += 1
                timestamp = int(time.time() * 1000)
                with self._pong_lock:
                    self._pong_event.clear()
                self._send(pdu.build_ping(self.ping_seq, timestamp))

                if not self._pong_event.wait(constants.HEARTBEAT_TIMEOUT_S):
                    print(f"[{self.player_id}] Heartbeat timeout — disconnecting")
                    self.running = False
                    break
            except (framing.ConnectionClosed, framing.FramingError, OSError):
                self.running = False
                break

    def _handle_pong(self, incoming: dict) -> None:
        with self._pong_lock:
            self._pong_event.set()

    # ------------------------------------------------------------------
    # Outbound actions
    # ------------------------------------------------------------------

    def send_player_ready(self) -> None:
        self._send(pdu.build_player_ready(
            self._next_client_seq(), self.player_id, self.deck_list,
        ))

    def send_mulligan_choice(self, keep: bool, cards_to_bottom: list[str]) -> None:
        if self.action_token is None:
            raise ValueError("No action token for mulligan")
        self._send(pdu.build_mulligan_choice(
            self.action_token, keep, cards_to_bottom,
        ))

    def send_priority_pass(self) -> None:
        if self.action_token is None:
            raise ValueError("No action token for priority pass")
        self._send(pdu.build_priority_pass(self.action_token))

    def send_cast_spell(
        self, card_id: str, targets: list[str], mana_payment: dict,
    ) -> None:
        if self.action_token is None:
            raise ValueError("No action token for cast")
        self._send(pdu.build_cast_spell(
            self.action_token, card_id, targets, mana_payment,
        ))

    def send_play_land(self, card_id: str) -> None:
        if self.action_token is None:
            raise ValueError("No action token for play land")
        self._send(pdu.build_play_land(self.action_token, card_id))

    def send_declare_attackers(self, attackers: list[dict]) -> None:
        if self.action_token is None:
            raise ValueError("No action token for declare attackers")
        self._send(pdu.build_declare_attackers(self.action_token, attackers))

    def send_declare_blockers(self, blockers: list[dict]) -> None:
        if self.action_token is None:
            raise ValueError("No action token for declare blockers")
        self._send(pdu.build_declare_blockers(self.action_token, blockers))

    def send_assign_damage_order(self, attacker_id: str, blocker_order: list[str]) -> None:
        if self.action_token is None:
            raise ValueError("No action token for damage order")
        self._send(pdu.build_assign_damage_order(
            self.action_token, attacker_id, blocker_order,
        ))

    def send_discard(self, card_ids: list[str]) -> None:
        if self.action_token is None:
            raise ValueError("No action token for discard")
        self._send(pdu.build_discard(self.action_token, card_ids))

    def send_concede(self) -> None:
        seq = self.last_server_seq if self.last_server_seq is not None else self._next_client_seq()
        self._send(pdu.build_concede(seq, self.player_id))

    def send_trigger_order_response(self, ordered_trigger_ids: list[str]) -> None:
        if self.action_token is None:
            raise ValueError("No action token for trigger order")
        self._send(pdu.build_trigger_order_response(
            self.action_token, ordered_trigger_ids,
        ))

    def send_trigger_choice_response(
        self, trigger_id: str, accept: bool, chosen_target: str | None = None,
    ) -> None:
        if self.action_token is None:
            raise ValueError("No action token for trigger choice")
        self._send(pdu.build_trigger_choice_response(
            self.action_token, trigger_id, accept, chosen_target,
        ))

    # ------------------------------------------------------------------
    # Inbound dispatch
    # ------------------------------------------------------------------

    def _track_server_seq(self, incoming: dict) -> None:
        seq = incoming.get("seq_num")
        if isinstance(seq, int):
            self.last_server_seq = seq

    def handle_pdu(self, incoming: dict) -> None:
        self._track_server_seq(incoming)
        ptype = incoming.get("type")

        if ptype == "GAME_STATE_UPDATE":
            self.replace_state(incoming["state"])
            phase = self.state.get("phase") if self.state else None

            if phase in ("MULLIGAN", "CLEANUP"):
                self.action_token = incoming["seq_num"]

            self.render()

            if (
                phase == "MULLIGAN"
                and self.state.get("hand") is not None
                and not self.state.get("mulligan_kept", False)
            ):
                self._prompt_mulligan()
            elif self.pending_discard:
                self._prompt_discard()

        elif ptype == "PHASE_TRANSITION":
            self.current_phase = incoming["to_phase"]
            if incoming["to_phase"] in COMBAT_PHASES:
                self.action_token = incoming["seq_num"]
            print(f"[{self.player_id}] Phase: {incoming['from_phase']} → "
                  f"{incoming['to_phase']} (turn {incoming['turn']})")
            if incoming["to_phase"] == "ASSIGN_DAMAGE_ORDER":
                if self.player_id == incoming.get("active_player"):
                    self._prompt_assign_damage_order()
            elif incoming["to_phase"] == "DECLARE_ATTACKERS":
                if self.player_id == incoming.get("active_player"):
                    self._prompt_declare_attackers()
            elif incoming["to_phase"] == "DECLARE_BLOCKERS":
                if self.player_id != incoming.get("active_player"):
                    self._prompt_declare_blockers()

        elif ptype == "PRIORITY_GRANT":
            grantee = incoming["player_id"]
            self.action_token = incoming["seq_num"]
            self.holds_priority = grantee == self.player_id
            if self.holds_priority:
                print(f"[{self.player_id}] *** You have priority (token={self.action_token}) ***")
                self._prompt_priority_action()
            else:
                print(f"[{self.player_id}] Priority granted to {grantee}")

        elif ptype == "ERROR":
            print(f"[{self.player_id}] ERROR {incoming.get('code')}: "
                  f"{incoming.get('message')}")
            rejected = incoming.get("rejected_action")
            if rejected:
                print(f"  Rejected: {rejected}")
            if rejected and rejected.get("type") == "MULLIGAN_CHOICE" and self.action_token is not None:
                self._prompt_mulligan()

            rejected_type = rejected.get("type")
            if rejected_type == "DECLARE_ATTACKERS":
                self._prompt_declare_attackers()
            elif rejected_type == "DECLARE_BLOCKERS":
                self._prompt_declare_blockers()
            elif rejected_type == "ASSIGN_DAMAGE_ORDER":
                self._prompt_assign_damage_order()
            elif rejected_type == "MULLIGAN_CHOICE":
                self.mulligan_submitted = False
                self._prompt_mulligan()

        elif ptype == "STACK_PUSH":
            print(f"[{self.player_id}] Stack push: {incoming.get('source')} "
                  f"({incoming.get('stack_item_id')})")

        elif ptype == "STACK_RESOLVE":
            print(f"[{self.player_id}] Stack resolve: {incoming.get('stack_item_id')} "
                  f"→ {incoming.get('result')}")
            for change in incoming.get("state_changes", []):
                print(f"  {change}")

        elif ptype == "COMBAT_DAMAGE_RESULT":
            print(f"[{self.player_id}] Combat damage:")
            for event in incoming.get("damage_events", []):
                print(f"  {event['source']} → {event['target']} for {event['amount']}")
            died = incoming.get("creatures_died", [])
            if died:
                print(f"  Creatures died: {died}")
            print(f"  Life totals: {incoming.get('life_totals', {})}")

        elif ptype == "TRIGGER_ORDER":
            if incoming.get("player_id") == self.player_id:
                self.pending_trigger_order = incoming
                self.action_token = incoming["seq_num"]
                self._prompt_trigger_order(incoming)

        elif ptype == "TRIGGER_CHOICE":
            self.pending_trigger_choice = incoming
            self.action_token = incoming["seq_num"]
            self._prompt_trigger_choice(incoming)

        elif ptype == "GAME_OVER":
            print(f"[{self.player_id}] GAME OVER — winner: {incoming.get('winner_id')} "
                  f"reason: {incoming.get('reason')}")
            self.holds_priority = False

        elif ptype == "PONG":
            self._handle_pong(incoming)

        elif ptype == "GAME_START":
            print(f"[{self.player_id}] GAME START")

            self.state = incoming.get("state", {})
            self.current_phase = self.state.get("phase")

            if "seq_num" in incoming:
                self.action_token = incoming["seq_num"]

            if self.state:
                self.render()

        else:
            if self.verbose:
                print(f"[{self.player_id}] Unhandled PDU: {ptype}")

    def _controller_of(self, permanent_id: str) -> str | None:
        if self.state is None:
            return None
        for owner, permanents in self.state.get("battlefield", {}).items():
            for perm in permanents:
                if perm.get("id") == permanent_id:
                    return owner
        return None

    # ------------------------------------------------------------------
    # CLI prompts (hybrid — no local legality checks)
    # ------------------------------------------------------------------

    def _prompt_input(self, prompt: str) -> str:
        try:
            return input(prompt).strip()
        except EOFError:
            return "pass"

    def _prompt_priority_action(self) -> None:
        if not self.holds_priority:
            return

        phase = self.current_phase or (self.state or {}).get("phase", "")

        if phase == "DECLARE_ATTACKERS" and self.player_id == (self.state or {}).get("active_player"):
            self._prompt_declare_attackers()
            return

        if phase == "DECLARE_BLOCKERS" and self.player_id != (self.state or {}).get("active_player"):
            self._prompt_declare_blockers()
            return

        if self.pending_discard:
            self._prompt_discard()
            return

        print("\nActions: [1] pass  [2] cast spell  [3] play land  "
              "[4] concede  [5] activate ability")
        choice = self._prompt_input("Choose action: ")

        if choice in ("1", "pass", ""):
            self.send_priority_pass()
        elif choice in ("2", "cast"):
            self._prompt_cast_spell()
        elif choice in ("3", "land"):
            self._prompt_play_land()
        elif choice in ("4", "concede"):
            self.send_concede()
        elif choice in ("5", "activate"):
            self._prompt_activate_ability()
        else:
            self.send_priority_pass()

    def _prompt_cast_spell(self) -> None:
        card_id = self._prompt_input("Card id to cast: ")
        if not card_id:
            self.send_priority_pass()
            return
        targets_raw = self._prompt_input("Targets (comma-separated, or empty): ")
        targets = [t.strip() for t in targets_raw.split(",") if t.strip()]
        mana_raw = self._prompt_input("Mana payment (e.g. R:1 or U:2): ")
        mana_payment = self._parse_mana(mana_raw)
        self.send_cast_spell(card_id, targets, mana_payment)

    def _prompt_play_land(self) -> None:
        card_id = self._prompt_input("Land card id: ")
        if card_id:
            self.send_play_land(card_id)
        else:
            self.send_priority_pass()

    def _prompt_activate_ability(self) -> None:
        source_id = self._prompt_input("Source permanent id: ")
        if not source_id:
            self.send_priority_pass()
            return
        idx = self._prompt_input("Ability index (0): ") or "0"
        targets_raw = self._prompt_input("Targets (comma-separated, or empty): ")
        targets = [t.strip() for t in targets_raw.split(",") if t.strip()]
        tap_raw = self._prompt_input("Tap as cost? (y/n): ")
        cost = {"tap": tap_raw.lower() in ("y", "yes", "1"), "mana": {}}
        self._send(pdu.build_activate_ability(
            self.action_token, source_id, int(idx), targets, cost,
        ))

    def _prompt_declare_attackers(self) -> None:
        print("Declare attackers (empty = no attack)")
        raw = self._prompt_input(
            "Attackers as creature_id:target pairs, comma-separated "
            "(e.g. goblin_guide_001:player_2): ",
        )
        attackers = []
        if raw:
            for pair in raw.split(","):
                pair = pair.strip()
                if ":" in pair:
                    cid, target = pair.split(":", 1)
                    attackers.append({"creature_id": cid.strip(), "target": target.strip()})
        self.send_declare_attackers(attackers)

    def _prompt_declare_blockers(self) -> None:
        print("Declare blockers (empty = no blocks)")
        raw = self._prompt_input(
            "Blockers as creature_id:blocking_id pairs, comma-separated: ",
        )
        blockers = []
        if raw:
            for pair in raw.split(","):
                pair = pair.strip()
                if ":" in pair:
                    cid, blocking = pair.split(":", 1)
                    blockers.append({"creature_id": cid.strip(), "blocking_id": blocking.strip()})
        self.send_declare_blockers(blockers)

    def _prompt_mulligan(self) -> None:
        hand = (self.state or {}).get("hand", [])
        mulligan_count=(self.state or {}).get("mulligan_count",0)
        print(f"    Mulligan? Hand ({len(hand)}): {hand}")

        if mulligan_count:
            print(f"(Mulligan count: {mulligan_count} card(s).)")
        raw=self._prompt_input("Keep hand? (y/n): ")
        keep=raw.lower() in ("y", "yes", "1", "")
        cards_to_bottom:list[str]=[]

        if keep:
            if mulligan_count:
                print(f"Already mulliganed {mulligan_count} time(s) — "
                    f"keeping requires bottoming {mulligan_count} card(s).")
            print("-" * 60)

            raw = self._prompt_input("Keep hand? (y/n): ")
            keep = raw.lower() in ("y", "yes", "1", "")
            cards_to_bottom: list[str] = []

            if keep and mulligan_count:
                raw_bottom = self._prompt_input(
                    f"Card id(s) to bottom ({mulligan_count} required, comma-separated): ",
                )
                cards_to_bottom = [c.strip() for c in raw_bottom.split(",") if c.strip()]
            elif keep:
                raw_bottom = self._prompt_input(
                    "Card id(s) to bottom (comma-separated, empty if none): ",
                )
                cards_to_bottom = [c.strip() for c in raw_bottom.split(",") if c.strip()]

        self.send_mulligan_choice(keep,cards_to_bottom)
        self.mulligan_submitted=keep

    def _prompt_assign_damage_order(self) -> None:
        raw_attacker = self._prompt_input("Attacker id for damage order: ")
        if not raw_attacker:
            return
        raw_order = self._prompt_input("Blocker order (comma-separated ids): ")
        blocker_order = [b.strip() for b in raw_order.split(",") if b.strip()]
        self.send_assign_damage_order(raw_attacker, blocker_order)

    def _prompt_discard(self) -> None:
        hand = (self.state or {}).get("hand", [])
        print(f"Discard required — hand ({len(hand)}): {hand}")
        raw = self._prompt_input("Card ids to discard (comma-separated): ")
        card_ids = [c.strip() for c in raw.split(",") if c.strip()]
        if card_ids:
            self.send_discard(card_ids)

    def _prompt_trigger_order(self, incoming: dict) -> None:
        ids = incoming.get("trigger_ids", [])
        print(f"Order triggers: {ids}")
        raw = self._prompt_input("Enter trigger ids in preferred stack order (comma-separated): ")
        ordered = [t.strip() for t in raw.split(",") if t.strip()]
        self.send_trigger_order_response(ordered)

    def _prompt_trigger_choice(self, incoming: dict) -> None:
        print(f"Trigger choice: {incoming.get('effect_summary', '')}")
        raw = self._prompt_input("Accept? (y/n): ")
        accept = raw.lower() in ("y", "yes", "1")
        chosen = None
        if accept and incoming.get("requires_target"):
            chosen = self._prompt_input("Chosen target: ") or None
        self.send_trigger_choice_response(incoming["trigger_id"], accept, chosen)

    @staticmethod
    def _parse_mana(raw: str) -> dict:
        payment: dict = {}
        if not raw:
            return payment
        for part in raw.split(","):
            part = part.strip()
            if ":" in part:
                color, amount = part.split(":", 1)
                payment[color.strip()] = int(amount.strip())
        return payment

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Connect, send PLAYER_READY, then recv until disconnect."""
        self.connect()
        print(f"[{self.player_id}] Connected to {self.host}:{self.port}")
        self.send_player_ready()
        print(f"[{self.player_id}] Sent PLAYER_READY")

        while self.running and self.sock is not None:
            try:
                incoming = framing.recv_pdu(self.sock, label=self.player_id)
                self.handle_pdu(incoming)
            except framing.ConnectionClosed:
                print(f"[{self.player_id}] Connection closed")
                break
            except framing.FramingError as exc:
                print(f"[{self.player_id}] Framing error: {exc}")
                break

        self.disconnect()