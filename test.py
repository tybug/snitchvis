from dataclasses import dataclass
from pathlib import Path
import re
from datetime import datetime

from snitchvis import SnitchvisApp

@dataclass
class Snitch:
    x: int
    y: int

@dataclass
class Event:
    username: str
    snitch_name: str
    namelayer_group: str
    x: int
    y: int
    z: int
    # time in ms
    t: int


class Ping(Event):
    pass
class Logout(Event):
    pass
class Login(Event):
    pass


events = []
snitches = [Snitch(-6870, 3968), Snitch(-6870, 2358)]

input_file = Path(__file__).parent / "input.txt"
with open(input_file, encoding="utf8") as f:
    raw_events = f.readlines()

pattern = r"\[(.*?)\] \[(.*?)\] (\w*?) (?:is|logged out|logged in) at (.*?) \((.*?),(.*?),(.*?)\)"

for raw_event in raw_events:
    if "is at" in raw_event:
        EventClass = Ping
    if "logged out" in raw_event:
        EventClass = Logout
    if "logged in" in raw_event:
        EventClass = Login

    result = re.match(pattern, raw_event)
    time_str, nl_group, username, snitch_name, x, y, z = result.groups()
    time = datetime.strptime(time_str, "%H:%M:%S")
    # time = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")

    event = EventClass(username, snitch_name, nl_group, x, y, z, time)
    events.append(event)

# normalize all event times to the earliest event, and convert to ms
earliest_event_t = min(event.t for event in events)

for event in events:
    event.t = int((event.t - earliest_event_t).total_seconds() * 1000)


vis = SnitchvisApp(snitches, events)
vis.exec()
