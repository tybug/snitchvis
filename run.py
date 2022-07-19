import time
t_start = time.time()

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
parser.add_argument("-p", "--pixels", help="pixel width of the generated "
    "images. Only has an effect when -r/--record is passed", default=500,
    type=int)
parser.add_argument("-f", "--fps", help="frames per second of the generated "
    "video", default=30, type=int)
parser.add_argument("-d", "--duration", help="duration of the generated video, "
    "in seconds", default=10, type=int)
parser.add_argument("--fade", help="percentage of the video snitch pings "
    "should be visible for", default=5, type=float)
args = parser.parse_args()

event_file = Path(".") / args.input
snitch_db = Path(".") / args.snitch_db
event_start_td, events = parse_events(event_file)
snitches = parse_snitches(snitch_db, events)
users = create_users(events)

# args
show_all_snitches = args.all_snitches
size = args.pixels
fps = args.fps
duration = args.duration
event_fade_percentage = args.fade

t_parse = time.time()

if args.record:
    vis = SnitchVisRecord(snitches, events, users, event_start_td, size, fps,
        duration, show_all_snitches, event_fade_percentage)
else:
    vis = SnitchvisApp(snitches, events, users, event_start_td,
        speeds=[0.25, 0.5, 1, 2.5, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000],
        show_all_snitches=show_all_snitches)

t_instantiation = time.time()

vis.exec()

print(f"time (event/snitch parsing) {t_parse - t_start}")
print(f"time (vis instantiation) {t_instantiation - t_parse}")
print(f"time (rendering) {vis.rendering_end - vis.rendering_start}")
print(f"time (ffmpeg stitching) {vis.ffmpeg_end - vis.ffmpeg_start}")
print(f"time (total): {time.time() - t_start}")

# TODO handle overlapping events on the same snitch
# TODO try copying the buffer per frame and only redrawing what's changed
