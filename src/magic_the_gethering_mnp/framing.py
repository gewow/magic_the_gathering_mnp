import json
import struct
import constants

MAX_PDU_SIZE = 65535


class FramingError(Exception):
    pass


#specific exception for clean socket close handling
class ConnectionClosed(ConnectionError):
    pass


def send_pdu(sock, pdu: dict, label=None):
    if not isinstance(pdu, dict):
        raise FramingError("PDU must be dict")

    payload = json.dumps(pdu, separators=(",", ":")).encode("utf-8")

    if len(payload) > MAX_PDU_SIZE:
        raise FramingError("PDU too large")

    header = struct.pack(">I", len(payload))
    sock.sendall(header + payload)

    if constants.is_verbose():
        prefix = f"[SEND:{label}]" if label else "[SEND]"
        print(prefix, pdu)


def recv_exact(sock, n, label=None):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionClosed("Socket closed cleanly")
        data += chunk
    return data


def recv_pdu(sock, label=None):
    header = recv_exact(sock, 4, label)
    length = struct.unpack(">I", header)[0]

    if length == 0:
        raise FramingError("Empty PDU")

    if length > MAX_PDU_SIZE:
        raise FramingError("PDU too large")

    payload = recv_exact(sock, length, label)

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise FramingError("Invalid UTF-8")

    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        raise FramingError("Invalid JSON")

    if not isinstance(obj, dict):
        raise FramingError("PDU must be JSON object")

    if constants.is_verbose():
        prefix = f"[RECV:{label}]" if label else "[RECV]"
        print(prefix, obj)

    return obj