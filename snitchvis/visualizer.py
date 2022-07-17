from dataclasses import dataclass
import re
from datetime import datetime
import sqlite3
from subprocess import Popen, PIPE

import numpy as np
from PIL.ImageQt import fromqimage
from PyQt6.QtGui import QPalette, QColor, QShortcut, QImage
from PyQt6.QtWidgets import QMainWindow, QApplication
from PyQt6.QtCore import Qt, QTimer, QRect

from snitchvis.frame_renderer import FrameRenderer
from snitchvis.interface import Interface

PREVIOUS_ERRSTATE = np.seterr('raise')

if "profile" not in globals():
    def profile(f):
        return f

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

    # set by frame_renderer, TODO extract out
    visible: bool = None

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


@dataclass
class User:
    username: str
    color: QColor
    # init with an empty qrect, we'll set the actual info pos later (when used
    # by Renderer anyway)
    # TODO extract this out, this shouldn't live in the user class
    info_pos_rect: QRect = QRect(0, 0, 0, 0)
    enabled: bool = True

def parse_events(path):
    events = []

    with open(path, encoding="utf8") as f:
        raw_events = f.readlines()

    pattern = r"\[(.*?)\] \[(.*?)\] (\w*?) (?:is|logged out|logged in) at (.*?) \((.*?),(.*?),(.*?)\)"

    for raw_event in raw_events:
        if "is at" in raw_event:
            EventClass = Ping
        elif "logged out" in raw_event:
            EventClass = Logout
        elif "logged in" in raw_event:
            EventClass = Login
        else:
            # ignore lines which don't match the format
            continue

        result = re.match(pattern, raw_event)
        time_str, nl_group, username, snitch_name, x, y, z = result.groups()
        x = int(x)
        y = int(y)
        z = int(z)
        try:
            time = datetime.strptime(time_str, "%H:%M:%S")
        except:
            time = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")

        # minecraft uses y as height, to preserve my sanity we're going to swap and
        # use z as height
        event = EventClass(username, snitch_name, nl_group, x, z, y, time)
        events.append(event)

    event_start_td = min(event.t for event in events)
    # normalize all event times to the earliest event, and convert to ms
    for event in events:
        event.t = int((event.t - event_start_td).total_seconds() * 1000)
    events = sorted(events, key = lambda event: event.t)

    return event_start_td, events

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

def create_users(events):
    users = []
    usernames = {event.username for event in events}
    for i, username in enumerate(usernames):
        color = QColor().fromHslF(i / len(usernames), 0.75, 0.5)
        user = User(username, color)
        users.append(user)

    return users


class Snitchvis(QMainWindow):
    def __init__(self, snitches, events, users, event_start_td, *,
        speeds=[0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 3.0, 5.0, 10.0],
        start_speed=1, show_all_snitches=False
    ):
        super().__init__()

        self.setAutoFillBackground(True)
        self.setWindowTitle("SnitchVis")

        self.interface = Interface(snitches, events, users, event_start_td,
            speeds, start_speed, show_all_snitches)
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
    ``speeds`` must contain ``start_speed``.
    """
    def __init__(self, snitches, events, users, event_start_td, *,
        speeds=[0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 3.0, 5.0, 10.0],
        start_speed=1, show_all_snitches=False
    ):
        super().__init__([])
        self.setStyle("Fusion")
        self.setApplicationName("Circlevis")

        self.visualizer = None
        self.snitches = snitches
        self.events = events
        self.users = users
        self.event_start_td = event_start_td
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
        self.visualizer = Snitchvis(self.snitches, self.events, self.users,
            self.event_start_td, speeds=self.speeds, start_speed=self.start_speed,
            show_all_snitches=self.show_all_snitches)
        self.visualizer.interface.renderer.loaded_signal.connect(self.on_load)
        self.visualizer.show()
        super().exec()

    def set_palette(self):
        accent = QColor(71, 174, 247)
        dark_p = QPalette()

        cg = QPalette.ColorGroup
        cr = QPalette.ColorRole
        dark_p.setColor(cg.Normal,     cr.Window, QColor(53, 53, 53))
        dark_p.setColor(cg.Normal,     cr.WindowText, Qt.GlobalColor.white)
        dark_p.setColor(cg.Normal,     cr.Base, QColor(25, 25, 25))
        dark_p.setColor(cg.Normal,     cr.AlternateBase, QColor(53, 53, 53))
        dark_p.setColor(cg.Normal,     cr.ToolTipBase, QColor(53, 53, 53))
        dark_p.setColor(cg.Normal,     cr.ToolTipText, Qt.GlobalColor.white)
        dark_p.setColor(cg.Normal,     cr.Text, Qt.GlobalColor.white)
        dark_p.setColor(cg.Normal,     cr.Button, QColor(53, 53, 53))
        dark_p.setColor(cg.Normal,     cr.ButtonText, Qt.GlobalColor.white)
        dark_p.setColor(cg.Normal,     cr.BrightText, Qt.GlobalColor.red)
        dark_p.setColor(cg.Normal,     cr.Highlight, accent)
        # also change for inactive (when app is in background)
        dark_p.setColor(cg.Inactive,   cr.Window, QColor(53, 53, 53))
        dark_p.setColor(cg.Inactive,   cr.WindowText, Qt.GlobalColor.white)
        dark_p.setColor(cg.Inactive,   cr.Base, QColor(25, 25, 25))
        dark_p.setColor(cg.Inactive,   cr.AlternateBase, QColor(53, 53, 53))
        dark_p.setColor(cg.Inactive,   cr.ToolTipBase, QColor(53, 53, 53))
        dark_p.setColor(cg.Inactive,   cr.ToolTipText, Qt.GlobalColor.white)
        dark_p.setColor(cg.Inactive,   cr.Text, Qt.GlobalColor.white)
        dark_p.setColor(cg.Inactive,   cr.Button, QColor(53, 53, 53))
        dark_p.setColor(cg.Inactive,   cr.ButtonText, Qt.GlobalColor.white)
        dark_p.setColor(cg.Inactive,   cr.BrightText, Qt.GlobalColor.red)
        dark_p.setColor(cg.Inactive,   cr.Highlight, accent)

        dark_p.setColor(cg.Inactive,   cr.Highlight, Qt.GlobalColor.lightGray)
        dark_p.setColor(cg.Normal,     cr.HighlightedText, Qt.GlobalColor.black)
        dark_p.setColor(cg.Disabled,   cr.Text, Qt.GlobalColor.darkGray)
        dark_p.setColor(cg.Disabled,   cr.ButtonText, Qt.GlobalColor.darkGray)
        dark_p.setColor(cg.Disabled,   cr.Highlight, Qt.GlobalColor.darkGray)
        dark_p.setColor(cg.Disabled,   cr.Base, QColor(53, 53, 53))
        dark_p.setColor(cg.Normal,     cr.Link, accent)
        dark_p.setColor(cg.Normal,     cr.LinkVisited, accent)
        dark_p.setColor(cg.Inactive,   cr.Link, accent)
        dark_p.setColor(cg.Inactive,   cr.LinkVisited, accent)

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


class SnitchVisRecord(QApplication):
    def __init__(self, snitches, events, users, show_all_snitches,
        event_start_td):
        # https://stackoverflow.com/q/13215120
        super().__init__(['-platform', 'minimal'])

        self.snitches = snitches
        self.events = events
        self.users = users
        self.show_all_snitches = show_all_snitches
        self.event_start_td = event_start_td

        QTimer.singleShot(0, self.start)

    def start(self):
        pass

    @profile
    def exec(self):
        renderer = FrameRenderer(None, self.snitches, self.events, self.users,
            self.show_all_snitches, self.event_start_td)

        images = []
        # frames per second
        framerate = 30
        # seconds
        video_duration = 10

        max_t = max(e.t for e in self.events)
        actual_duration = max_t / 1000

        # our video is `actual_duration` seconds long, and we need to compress
        # that into `video_duration` seconds at `framerate` fps.
        # we have `framerate * video_duration` frames to work with, and each
        # frame needs to take `actual_duration / num_frames` seconds

        num_frames = int(video_duration * framerate)
        # in ms
        frame_duration = (actual_duration / num_frames) * 1000

        for i in range(num_frames):
            print(f"rendering image {i} / {num_frames}")
            image = QImage(1000, 1000, QImage.Format.Format_RGB32)
            image.fill(Qt.GlobalColor.black)

            renderer.paint_object = image
            renderer.t = int(i * frame_duration)
            renderer.render()

            # TODO this is relatively expensive (5% of function time), we can
            # probably do better by only saving to a buffer and not creating a
            # full PIL QImage object. Then stream that buffer to the ffmpeg
            # pipe instead of im.save.
            im = fromqimage(image)
            images.append(im)

        # https://stackoverflow.com/a/13298538
        # -y overwrites output file if exists
        # -r specifies framerate (frames per second)
        p = Popen(["ffmpeg", "-y", "-f", "image2pipe", "-r", str(framerate),
            "-vcodec", "mjpeg", "-pix_fmt", "yuv420p", "-i", "-", "-vf",
            "scale=1000:1000", "out_ffmpeg.mp4"],
            stdin=PIPE)

        for i, im in enumerate(images):
            print(f"saving image {i} to stdin")
            im.save(p.stdin, "JPEG")
        p.stdin.close()

        print("converting images to video with ffmpeg")
        p.wait()

        QApplication.quit()
