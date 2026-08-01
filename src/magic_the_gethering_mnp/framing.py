import json
import socket
import struct

import constants


class FramingError(Exception):
    """Raised when a frame can't be sent/received/parsed correctly."""
    pass


class ConnectionClosed(Exception):
    """Raised when the peer closed the connection (recv returned 0 bytes)."""
    pass


def _log(direction: str, pdu: dict, label: str = "") -> None:
    if not constants.is_verbose():
        return
    tag = f"[{label}] " if label else ""
    ptype = pdu.get("type", "?")
    seq = pdu.get("seq_num", "?")
    print(f"{tag}[{direction}] type={ptype} seq_num={seq} :: {pdu}")


def _recv_exact(sock: socket.socket, num_bytes: int) -> bytes:
    chunks = []
    remaining = num_bytes
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionClosed("Peer closed the connection")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def send_pdu(sock: socket.socket, pdu: dict, label: str = "") -> None:
    payload = json.dumps(pdu).encode("utf-8")

    if len(payload) > constants.MAX_PDU_SIZE:
        raise FramingError(
            f"PDU of {len(payload)} bytes exceeds MAX_PDU_SIZE "
            f"({constants.MAX_PDU_SIZE}); type={pdu.get('type')}"
        )

    header = struct.pack("!I", len(payload))  # "!I" = network-order unsigned int
    sock.sendall(header + payload)
    _log("SEND", pdu, label)


def recv_pdu(sock: socket.socket, label: str = "") -> dict:
    header = _recv_exact(sock, constants.LENGTH_PREFIX_BYTES)
    (length,) = struct.unpack("!I", header)

    if length > constants.MAX_PDU_SIZE:
        raise FramingError(
            f"Incoming PDU declares {length} bytes, exceeds MAX_PDU_SIZE "
            f"({constants.MAX_PDU_SIZE})"
        )

    raw = _recv_exact(sock, length)

    try:
        pdu = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FramingError(f"Malformed JSON payload: {exc}") from exc

    if not isinstance(pdu, dict):
        raise FramingError("Decoded JSON payload is not an object")

    _log("RECV", pdu, label)
    return pdu