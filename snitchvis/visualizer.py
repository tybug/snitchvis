from dataclasses import dataclass
import re
from datetime import datetime
import sqlite3

import numpy as np
from PyQt6.QtGui import QPalette, QColor, QShortcut
from PyQt6.QtWidgets import QMainWindow, QApplication
from PyQt6.QtCore import Qt

from snitchvis.interface import Interface

PREVIOUS_ERRSTATE = np.seterr('raise')


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
    # events that occurred at this snitch
    events: list[Event]

    @staticmethod
    def from_row(row):
        # swap z and y for my sanity
        return Snitch(world=row[0], x=row[1], z=row[2], y=row[3],
            group_name=row[4], type=row[5], name=row[6], dormat_ts=row[7],
            cull_ts=row[8], last_seen_ts=row[9], created_ts=row[10],
            created_by_uuid=row[11], renamde_ts=row[12],
            renamed_by_uuid=row[13], lost_jalist_access_ts=row[14],
            broken_ts=row[15], gone_ts=row[16], tags=row[17], notes=row[18],
            events=[])

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

def parse_snitches(path, events):
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

    snitch_by_pos = {(snitch.x, snitch.y): snitch for snitch in snitches}
    for event in events:
        snitch = snitch_by_pos[(event.x, event.y)]
        snitch.events.append(event)
    return snitches



class Snitchvis(QMainWindow):
    def __init__(self, snitch_db, event_file,
        speeds=[0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 3.0, 5.0, 10.0],
        start_speed=1,
        show_all_snitches=False
    ):
        super().__init__()

        self.setAutoFillBackground(True)
        self.setWindowTitle("Visualizer")
        events = parse_events(event_file)
        snitches = parse_snitches(snitch_db, events)
        self.interface = Interface(snitches, events, speeds, start_speed,
            show_all_snitches)
        self.interface.renderer.loaded_signal.connect(self.on_load)
        self.setCentralWidget(self.interface)

        QShortcut(Qt.Key.Key_Space, self, self.interface.toggle_pause)
        QShortcut(Qt.Key.Key_Right, self,
            lambda: self.interface.change_frame(reverse=False))
        QShortcut(Qt.Key.Key_Left, self,
            lambda: self.interface.change_frame(reverse=True))
        QShortcut(Qt.Key.Key_Control + Qt.Key.Key_Right, self, self.interface.play_normal)
        QShortcut(Qt.Key.Key_Control + Qt.Key.Key_Left, self, self.interface.play_reverse)

        QShortcut(Qt.Key.Key_Up, self, self.interface.increase_speed)
        QShortcut(Qt.Key.Key_Down, self, self.interface.lower_speed)
        QShortcut(Qt.Key.Key_Escape, self, self.exit_fullscreen)
        QShortcut(Qt.Key.Key_Period, self, lambda: self.interface.change_by(1))
        QShortcut(Qt.Key.Key_Comma, self, lambda: self.interface.change_by(-1))

        from .renderer import (GAMEPLAY_WIDTH, GAMEPLAY_HEIGHT,
            GAMEPLAY_PADDING_WIDTH, GAMEPLAY_PADDING_HEIGHT)
        self.resize(int((GAMEPLAY_WIDTH + GAMEPLAY_PADDING_WIDTH * 2) * 1.4),
                    int((GAMEPLAY_HEIGHT + GAMEPLAY_PADDING_HEIGHT * 2) * 1.4))

    def closeEvent(self, event):
        super().closeEvent(event)
        self.interface.renderer.timer.stop()
        np.seterr(**PREVIOUS_ERRSTATE)

    def exit_fullscreen(self):
        self.setWindowState(Qt.WindowState.WindowNoState)

    def seek_to(self, timestamp):
        self.interface.renderer.seek_to(timestamp)

    def toggle_pause(self):
        self.interface.toggle_pause()

    def pause(self):
        self.interface.pause()

    def unpause(self):
        self.interface.unpause()

    def save_as_image(self):
        return self.grab().toImage()

    def on_load(self):
        """
        Will be called when the visualizer has completely loaded (including
        processing the beatmap, replays, sliders, and anything else) and is
        ready to display gameplay.
        """
        pass


class SnitchvisApp(QApplication):
    """
    ``speeds`` must contain ``start_speed``, ``1``, ``0.75``, and ``1.5``.
    """
    def __init__(self, snitch_db, event_file,
        speeds=[0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 3.0, 5.0, 10.0],
        start_speed=1,
        show_all_snitches=False
    ):
        super().__init__([])
        self.setStyle("Fusion")
        self.setApplicationName("Circlevis")

        self.visualizer = None
        self.snitch_db = snitch_db
        self.event_file = event_file
        self.speeds = speeds
        self.start_speed = start_speed
        self.show_all_snitches = show_all_snitches

    def exec(self):
        """
        Displays the visualizer and enters into the event loop, which will block
        the calling thread.
        """
        self.set_palette()
        # we can't create this in ``__init__`` because we can't instantiate a
        # ``QWidget`` before a ``QApplication``, so delay until here, which is
        # all it's necessary for.
        self.visualizer = Snitchvis(self.snitch_db, self.event_file, self.speeds,
            self.start_speed, self.show_all_snitches)
        self.visualizer.interface.renderer.loaded_signal.connect(self.on_load)
        self.visualizer.show()
        super().exec()

    def set_palette(self):
        accent = QColor(71, 174, 247)
        dark_p = QPalette()

        dark_p.setColor(QPalette.ColorGroup.Normal,   QPalette.ColorRole.Window, QColor(53, 53, 53))
        dark_p.setColor(QPalette.ColorGroup.Normal,   QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
        dark_p.setColor(QPalette.ColorGroup.Normal,   QPalette.ColorRole.Base, QColor(25, 25, 25))
        dark_p.setColor(QPalette.ColorGroup.Normal,   QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
        dark_p.setColor(QPalette.ColorGroup.Normal,   QPalette.ColorRole.ToolTipBase, QColor(53, 53, 53))
        dark_p.setColor(QPalette.ColorGroup.Normal,   QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
        dark_p.setColor(QPalette.ColorGroup.Normal,   QPalette.ColorRole.Text, Qt.GlobalColor.white)
        dark_p.setColor(QPalette.ColorGroup.Normal,   QPalette.ColorRole.Button, QColor(53, 53, 53))
        dark_p.setColor(QPalette.ColorGroup.Normal,   QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
        dark_p.setColor(QPalette.ColorGroup.Normal,   QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
        dark_p.setColor(QPalette.ColorGroup.Normal,   QPalette.ColorRole.Highlight, accent)
        dark_p.setColor(QPalette.ColorGroup.Inactive, QPalette.ColorRole.Highlight, Qt.GlobalColor.lightGray)
        dark_p.setColor(QPalette.ColorGroup.Normal,   QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
        dark_p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, Qt.GlobalColor.darkGray)
        dark_p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, Qt.GlobalColor.darkGray)
        dark_p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, Qt.GlobalColor.darkGray)
        dark_p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, QColor(53, 53, 53))
        dark_p.setColor(QPalette.ColorGroup.Normal,   QPalette.ColorRole.Link, accent)
        dark_p.setColor(QPalette.ColorGroup.Normal,   QPalette.ColorRole.LinkVisited, accent)

        self.setPalette(dark_p)

    def toggle_pause(self):
        self.visualizer.toggle_pause()

    def seek_to(self, timestamp):
        self.visualizer.seek_to(timestamp)

    def pause(self):
        self.visualizer.pause()

    def unpause(self):
        self.visualizer.unpause()

    def save_as_image(self):
        return self.visualizer.grab().toImage()

    def on_load(self):
        """
        Will be called when the visualizer has completely loaded (including
        processing the beatmap, replays, sliders, and anything else) and is
        ready to display gameplay.
        """
        pass
