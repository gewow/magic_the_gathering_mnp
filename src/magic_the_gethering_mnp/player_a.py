"""Player 1 client entry point."""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import constants
from client_state import MTGNPClient

# Deck from MTGNP Examples.pdf Step 1
PLAYER_A_DECK = [
    "lightning_bolt_001", "lightning_bolt_002", "lightning_bolt_003",
    "shock_001", "shock_002",
    "goblin_guide_001",
    "mountain_001", "mountain_002",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="MTGNP Player 1 client")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=constants.SERVER_PORT)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        constants.set_verbose(True)

    client = MTGNPClient(
        host=args.host,
        port=args.port,
        player_id="player_1",
        deck_list=PLAYER_A_DECK,
        verbose=args.verbose,
    )
    client.run()


if __name__ == "__main__":
    main()
