"""Player 2 client entry point."""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import constants
from client_state import MTGNPClient

# Deck from MTGNP Examples.pdf Step 3
PLAYER_B_DECK = [
    "counterspell_001", "counterspell_002",
    "gray_merchant_001", "gray_merchant_002",
    "island_001", "island_002",
    "swamp_001", "swamp_002",
]


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
