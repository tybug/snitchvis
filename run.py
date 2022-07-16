from pathlib import Path
from argparse import ArgumentParser

from snitchvis import (SnitchvisApp, SnitchVisRecord, parse_events,
    parse_snitches, create_users)

parser = ArgumentParser()
parser.add_argument("-a", "--all-snitches", help="show all snitches in the "
    "visualization, even those which weren't pinged", action="store_true",
    default=False)
parser.add_argument("-i", "--input", help="event file input to parse",
    required=True)
parser.add_argument("-s", "--snitch-db", help="snitch database (.sqlite) file "
    "to parse", required=True)
parser.add_argument("-r", "--record", help="record and output to a file "
    "instead o showing an interactive QApplication", default=False,
    action="store_true")
args = parser.parse_args()


# TODO handle overlapping events on the same snitch

event_file = Path(".") / args.input
snitch_db = Path(".") / args.snitch_db
event_start_td, events = parse_events(event_file)
snitches = parse_snitches(snitch_db, events)
users = create_users(events)
# whther to make our bounding box large enough to show all of our snitches
show_all_snitches = args.all_snitches

if args.record:
    vis = SnitchVisRecord(snitches, events, users, show_all_snitches,
        event_start_td)
else:
    vis = SnitchvisApp(events, snitches, users, event_start_td,
        [0.25, 0.5, 1, 2.5, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000],
        show_all_snitches)

vis.exec()
