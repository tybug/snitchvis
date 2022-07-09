from dataclasses import dataclass
from pathlib import Path
import re
from datetime import datetime
import sqlite3

from snitchvis import SnitchvisApp

# TODO add all fields
@dataclass
class DatabaseSnitch:
    x: int
    y: int
    z: int

@dataclass
class Snitch:
    world: str
    x: int
    y: int
    z: int
    group_name: str
    type: str
    name: str
    dormat_ts: int
    cull_ts: int
    last_seen_ts: int
    created_ts: int
    created_by_uuid: str
    renamde_ts: int
    renamed_by_uuid: str
    lost_jalist_access_ts: int
    broken_ts: int
    gone_ts: int
    tags: str
    notes: str

    @staticmethod
    def from_row(row):
        # swap z and y
        return Snitch(world=row[0], x=row[1], z=row[2], y=row[3],
            group_name=row[4], type=row[5], name=row[6], dormat_ts=row[7],
            cull_ts=row[8], last_seen_ts=row[9], created_ts=row[10],
            created_by_uuid=row[11], renamde_ts=row[12],
            renamed_by_uuid=row[13], lost_jalist_access_ts=row[14],
            broken_ts=row[15], gone_ts=row[16], tags=row[17], notes=row[18])

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



def parse_events(path):
    events = []

    with open(path, encoding="utf8") as f:
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
        x = int(x)
        y = int(y)
        z = int(z)
        time = datetime.strptime(time_str, "%H:%M:%S")
        # time = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")

        # minecraft uses y as height, to preserve my sanity we're going to swap and
        # use z as height
        event = EventClass(username, snitch_name, nl_group, x, z, y, time)
        events.append(event)

    # normalize all event times to the earliest event, and convert to ms
    earliest_event_t = min(event.t for event in events)

    for event in events:
        event.t = int((event.t - earliest_event_t).total_seconds() * 1000)

    return events

def parse_snitches(path):
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    rows = cur.execute("SELECT * FROM snitches_v2")
    snitches = []
    for row in rows:
        snitch = Snitch.from_row(row)
        # don't visualize snitches which are broken or gone
        if snitch.broken_ts or snitch.gone_ts:
            continue
        snitches.append(snitch)
    return snitches


event_file = Path(__file__).parent / "input.txt"
snitch_db_file = Path(__file__).parent / "snitches.sqlite"
events = parse_events(event_file)
snitches = parse_snitches(snitch_db_file)

vis = SnitchvisApp(snitches, events)
vis.exec()
