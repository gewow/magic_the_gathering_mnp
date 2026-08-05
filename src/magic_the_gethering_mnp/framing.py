import json
import struct
import constants

MAX_PDU_SIZE = 65535


class FramingError(Exception):
    pass


def send_pdu(sock, pdu: dict):
    if not isinstance(pdu, dict):
        raise FramingError("PDU must be dict")

    payload = json.dumps(pdu, separators=(",", ":")).encode("utf-8")

    if len(payload) > MAX_PDU_SIZE:
        raise FramingError("PDU too large")

    header = struct.pack(">I", len(payload))
    sock.sendall(header + payload)

    if constants.is_verbose():
        print("[SEND]", pdu)


def recv_exact(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("Socket closed")
        data += chunk
    return data


def recv_pdu(sock):
    header = recv_exact(sock, 4)
    length = struct.unpack(">I", header)[0]

    if length == 0:
        raise FramingError("Empty PDU")

    if length > MAX_PDU_SIZE:
        raise FramingError("PDU too large")

    payload = recv_exact(sock, length)

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
        print("[RECV]", obj)

    return obj