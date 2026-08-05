import argparse
import constants

parser = argparse.ArgumentParser()
parser.add_argument("--verbose", action="store_true")
args = parser.parse_args()

constants.set_verbose(args.verbose)