# server.py
import socket
import threading

from framing import recv_pdu, send_pdu, FramingError
import pdu
import constants

HOST = "0.0.0.0"
PORT = 4444
MAX_CLIENTS = 2

clients = []  # list of (socket, address)


def handle_client(conn, addr):
    try:
        while True:
            try:
                msg = recv_pdu(conn)
                if constants.is_verbose():
                    print(f"[SERVER] Received from {addr}: {msg}")

            except FramingError:
                #send INVALID_JSON error
                err = pdu.build_error(
                    seq_num=0,
                    code="INVALID_JSON",
                    message="Malformed JSON received",
                    rejected_action=None
                )
                send_pdu(conn, err)

            except ConnectionError:
                break

    finally:
        if constants.is_verbose():
            print(f"[SERVER] Client disconnected: {addr}")
        conn.close()


def start_server(verbose=False):
    constants.set_verbose(verbose)

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind((HOST, PORT))
    server_sock.listen()

    print(f"[SERVER] Listening on port {PORT}...")

    while True:
        conn, addr = server_sock.accept()

        #refuse 3rd client
        if len(clients) >= MAX_CLIENTS:
            if constants.is_verbose():
                print(f"[SERVER] Refusing connection from {addr} (server full)")

            #send error before closing
            err = pdu.build_error(
                seq_num=0,
                code="SERVER_FULL",
                message="Only 2 clients allowed",
                rejected_action=None
            )
            try:
                send_pdu(conn, err)
            except:
                pass

            conn.close()
            continue

        #accept client
        clients.append((conn, addr))
        if constants.is_verbose():
            print(f"[SERVER] Accepted {addr} ({len(clients)}/2)")

        thread = threading.Thread(target=handle_client, args=(conn, addr))
        thread.start()

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    start_server(verbose=args.verbose)