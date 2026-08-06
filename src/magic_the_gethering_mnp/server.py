import socket
import threading

from framing import recv_pdu, send_pdu, FramingError, ConnectionClosed
import pdu
import constants

HOST = "0.0.0.0"
PORT = 4444
MAX_CLIENTS = 2

shutdown_event = threading.Event()

players_ready = {}   # player_id -> conn
clients = []         # list of (conn, addr)


def handle_client(conn, addr):
    global clients
    label = f"{addr[0]}:{addr[1]}"
    conn.settimeout(1.0)  

    try:
        while not shutdown_event.is_set():
            try:
                msg = recv_pdu(conn, label=label)

                if msg.get("type") == "PING":
                    pong = {
                        "type": "PONG",
                        "seq_num": msg.get("seq_num"),
                        "timestamp": msg.get("timestamp")
                    }
                    send_pdu(conn, pong, label=label)
                    continue

                if msg.get("type") == "PLAYER_READY":
                    player_id = msg.get("player_id")
                    if player_id:
                        players_ready[player_id] = conn

                        if constants.is_verbose():
                            print(f"[SERVER] {player_id} is ready")

                if len(players_ready) == 2:
                    print("[SERVER] Both players ready. Starting game...")

                    start_msg = {
                        "type": "GAME_START",
                        "players": list(players_ready.keys())
                    }

                    for c, a in clients:
                        try:
                            send_pdu(c, start_msg, label=f"{a[0]}:{a[1]}")
                        except Exception:
                            pass

            except socket.timeout:
                continue

            except FramingError:
                err = pdu.build_error(
                    seq_num=0,
                    code="INVALID_JSON",
                    message="Malformed JSON received",
                    rejected_action=None
                )
                try:
                    send_pdu(conn, err, label=label)
                except Exception:
                    pass

            except ConnectionClosed:
                if constants.is_verbose():
                    print(f"[SERVER] Connection closed by {addr}")
                break

            except ConnectionError:
                break

    finally:
        if constants.is_verbose():
            print(f"[SERVER] Client disconnected: {addr}")

        conn.close()

        clients = [c for c in clients if c[0] != conn]


def start_server(verbose=False):
    constants.set_verbose(verbose)

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind((HOST, PORT))
    server_sock.listen()
    server_sock.settimeout(1.0)

    print(f"[SERVER] Listening on port {PORT}...")

    try:
        while not shutdown_event.is_set():
            try:
                conn, addr = server_sock.accept()
                conn.settimeout(1.0)

                label = f"{addr[0]}:{addr[1]}"

                if len(clients) >= MAX_CLIENTS:
                    if constants.is_verbose():
                        print(f"[SERVER] Refusing connection from {addr} (server full)")

                    err = pdu.build_error(
                        seq_num=0,
                        code=constants.ERROR_SERVER_FULL,
                        message="Only 2 clients allowed",
                        rejected_action=None
                    )

                    try:
                        send_pdu(conn, err, label=label)
                    except Exception:
                        pass

                    conn.close()
                    continue

                clients.append((conn, addr))

                if constants.is_verbose():
                    print(f"[SERVER] Accepted {addr} ({len(clients)}/2)")

                thread = threading.Thread(
                    target=handle_client,
                    args=(conn, addr),
                    daemon=True
                )
                thread.start()

            except socket.timeout:
                continue

    except KeyboardInterrupt:
        print("\n[SERVER] Shutting down gracefully...")
        shutdown_event.set()

    for conn, addr in clients:
        try:
            conn.close()
        except Exception:
            pass

    server_sock.close()
    print("[SERVER] Shutdown complete.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    start_server(verbose=args.verbose)