"""
test_framing.py

Proves framing.py actually works, using a REAL pair of connected
sockets (socket.socketpair() — built into Python, no network needed).
This is not a mock in the sense of fake behavior — it's a genuine
local socket pair, so if this test passes, framing.py will behave
identically over a real TCP connection.

Run with: python3 tests/test_framing.py
"""

import socket
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                 "src", "magic_the_gethering_mnp"))

import framing  # noqa: E402
import constants  # noqa: E402


def test_round_trip_simple_pdu():
    a, b = socket.socketpair()
    pdu = {"type": "PING", "seq_num": 1, "timestamp": 1234567890}
    framing.send_pdu(a, pdu, label="TEST-A")
    received = framing.recv_pdu(b, label="TEST-B")
    assert received == pdu, f"Round-trip mismatch: {received} != {pdu}"
    a.close()
    b.close()
    print("PASS: test_round_trip_simple_pdu")


def test_round_trip_nested_pdu():
    a, b = socket.socketpair()
    pdu = {
        "type": "GAME_STATE_UPDATE",
        "seq_num": 42,
        "state": {
            "turn": 3,
            "battlefield": {"player_1": [{"id": "mountain_001", "tapped": True}]},
            "stack": [],
        },
    }
    framing.send_pdu(a, pdu)
    received = framing.recv_pdu(b)
    assert received == pdu, "Nested dict round-trip failed"
    a.close()
    b.close()
    print("PASS: test_round_trip_nested_pdu")


def test_oversized_pdu_rejected():
    a, b = socket.socketpair()
    huge_pdu = {"type": "CAST_SPELL", "seq_num": 1, "targets": ["x"] * 100000}
    try:
        framing.send_pdu(a, huge_pdu)
        raised = False
    except framing.FramingError:
        raised = True
    assert raised, "Expected FramingError for oversized PDU, none was raised"
    a.close()
    b.close()
    print("PASS: test_oversized_pdu_rejected")


def test_connection_closed_detected():
    a, b = socket.socketpair()
    a.close()
    try:
        framing.recv_pdu(b)
        raised = False
    except (framing.ConnectionClosed, OSError):
        raised = True
    assert raised, "Expected ConnectionClosed/OSError when peer closed socket"
    b.close()
    print("PASS: test_connection_closed_detected")


def test_verbose_toggle_does_not_crash():
    constants.set_verbose(True)
    a, b = socket.socketpair()
    framing.send_pdu(a, {"type": "PONG", "seq_num": 1, "timestamp": 1})
    framing.recv_pdu(b)
    constants.set_verbose(False)
    a.close()
    b.close()
    print("PASS: test_verbose_toggle_does_not_crash (check output above for log lines)")


if __name__ == "__main__":
    test_round_trip_simple_pdu()
    test_round_trip_nested_pdu()
    test_oversized_pdu_rejected()
    test_connection_closed_detected()
    test_verbose_toggle_does_not_crash()
    print("\nAll framing.py tests passed.")
