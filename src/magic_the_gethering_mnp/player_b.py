"""Player 2 client entry point."""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import constants
from client_state import MTGNPClient

import json

_CARDS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cards.json")
with open(_CARDS_PATH, "r", encoding="utf-8") as f:
    _ALL_CARDS = list(json.load(f).keys())

# any subset between MIN_DECK_SIZE and MAX_DECK_SIZE works; 40 is a
# reasonable constructed-deck size
PLAYER_B_DECK = _ALL_CARDS[:40]


def main() -> None:
    parser = argparse.ArgumentParser(description="MTGNP Player 2 client")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=constants.SERVER_PORT)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        constants.set_verbose(True)

    client = MTGNPClient(
        host=args.host,
        port=args.port,
        player_id="player_2",
        deck_list=PLAYER_B_DECK,
        verbose=args.verbose,
    )
    client.run()


if __name__ == "__main__":
    main()
