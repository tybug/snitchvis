import time
t_start = time.time()

from pathlib import Path
from argparse import ArgumentParser

from PyQt6.QtWidgets import QApplication

from snitchvis import (SnitchvisApp, SnitchVisRecord, parse_events,
    parse_snitches, create_users, snitches_from_events, Config)

parser = ArgumentParser()
parser.add_argument("-a", "--all-snitches", help="show all snitches in the "
    "visualization, even those which weren't pinged", action="store_true",
    default=False)
parser.add_argument("-i", "--input", help="event file input to parse",
    required=True)
parser.add_argument("-s", "--snitch-db", help="snitch database (.sqlite) file "
    "to parse", required=True)
parser.add_argument("-r", "--record", help="record and output to a file "
    "instead of showing an interactive QApplication", default=False,
    action="store_true")
parser.add_argument("-p", "--pixels", help="width and height of the generated "
    "video, in pixels", default=500, type=int)
parser.add_argument("-f", "--fps", help="frames per second of the generated "
    "video", default=30, type=int)
parser.add_argument("-d", "--duration", help="duration of the generated video, "
    "in seconds", default=10, type=int)
parser.add_argument("--fade", help="what percentage of the video snitch pings "
    "should be visible for", default=10, type=float)
parser.add_argument("-o", "--output", help="filename to output to",
    default="out.mp4")
parser.add_argument("-m", "--mode", help="what mode to render in. One of "
    "square, line, heatmap. Defaults to square", default="square")
args = parser.parse_args()

event_file = Path(".") / args.input
snitch_db = Path(".") / args.snitch_db
events = parse_events(event_file, True)
snitches = set(parse_snitches(snitch_db))
# in case we have some event hits which aren't in our database
snitches |= set(snitches_from_events(events))
users = create_users(events)

# args
show_all_snitches = args.all_snitches
size = args.pixels
fps = args.fps
# convert seconds to ms
duration = args.duration * 1000
event_fade_percentage = args.fade
output_file = args.output
mode = args.mode
# TODO param for this
heatmap_percentage = 20

t_parse = time.time()

config = Config(snitches=snitches, events=events, users=users,
    show_all_snitches=show_all_snitches, mode=mode,
    heatmap_percentage=heatmap_percentage)

if args.record:
    # https://stackoverflow.com/q/13215120
    qapp = QApplication(['-platform', 'minimal'])
    vis = SnitchVisRecord(duration, size, fps, event_fade_percentage,
        output_file, config)
    vis.render()
else:
    vis = SnitchvisApp(config,
        speeds=[0.25, 0.5, 1, 2.5, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000]
    )
    vis.exec()


# TODO handle overlapping events on the same snitch
# TODO pad the first event like we did the last event? less of a concern but
# will probably make it look nicer due to seeing the fade in
