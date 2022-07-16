from pathlib import Path
from argparse import ArgumentParser

from snitchvis import SnitchvisApp

parser = ArgumentParser()
parser.add_argument("-a", "--all-snitches", help="show all snitches in the "
    "visualization, even those which weren't pinged", action="store_true",
    default=False)
parser.add_argument("-i", "--input", help="event file input to parse",
    required=True)
parser.add_argument("-s", "--snitch-db", help="snitch database (.sqlite) file "
    "to parse", required=True)
args = parser.parse_args()


event_file = Path(".") / args.input
snitch_db = Path(".") / args.snitch_db
# whther to make our bounding box large enough to show all of our snitches
show_all_snitches = args.all_snitches

vis = SnitchvisApp(event_file=event_file, snitch_db=snitch_db,
    speeds=[0.25, 0.5, 1, 2.5, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000],
    show_all_snitches=show_all_snitches)
vis.exec()

# TODO handle overlapping events on the same snitch
