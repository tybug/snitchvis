from dataclasses import dataclass
import re
from datetime import datetime
import sqlite3
from subprocess import Popen, PIPE

import numpy as np
from PyQt6.QtGui import QPalette, QColor, QShortcut, QImage
from PyQt6.QtWidgets import QMainWindow, QApplication
from PyQt6.QtCore import Qt, QRect, QBuffer

from snitchvis.frame_renderer import FrameRenderer
from snitchvis.interface import Interface

PREVIOUS_ERRSTATE = np.seterr('raise')

if "profile" not in __builtins__:
    def profile(f):
        return f

class InvalidEventException(Exception):
    pass

@dataclass
class Event:
    username: str
    snitch_name: str
    namelayer_group: str
    x: int
    y: int
    z: int
    t: datetime

    pattern_raw = (
        r"`\[(.*?)\]` `\[(.*?)\]` \*\*(\w*?)\*\* (?:is|logged out|logged in) "
        "at (.*?) \((.*?),(.*?),(.*?)\)"
    )

    pattern_display = (
        r"\[(.*?)\] \[(.*?)\] (\w*?) (?:is|logged out|logged in) at (.*?) "
        "\((.*?),(.*?),(.*?)\)"
    )

    @classmethod
    def parse(cls, raw_event, markdown=True):
        if "is at" in raw_event:
            EventClass = Ping
        elif "logged out" in raw_event:
            EventClass = Logout
        elif "logged in" in raw_event:
            EventClass = Login
        else:
            raise InvalidEventException()

        pattern = cls.pattern_raw if markdown else cls.pattern_display
        result = re.match(pattern, raw_event)
        if not result:
            raise InvalidEventException()
        time_str, nl_group, username, snitch_name, x, y, z = result.groups()
        x = int(x)
        y = int(y)
        z = int(z)
        # try both date formats, TODO make this cleaner (less nesting)
        try:
            time = datetime.strptime(time_str, "%H:%M:%S")
        except:
            try:
                time = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            except:
                raise InvalidEventException()

        # minecraft uses y as height, to preserve my sanity we're going to swap
        # and use z as height
        return EventClass(username, snitch_name, nl_group, x, z, y, time)

@dataclass
class Snitch:
    world: str
    x: int
    y: int
    z: int
    group_name: str
    type: str
    name: str
    dormant_ts: int
    cull_ts: int
    first_seen_ts: int
    last_seen_ts: int
    created_ts: int
    created_by_uuid: str
    renamed_ts: int
    renamed_by_uuid: str
    lost_jalist_access_ts: int
    broken_ts: int
    gone_ts: int
    tags: str
    notes: str

    @staticmethod
    def from_snitchmod(row):
        # swap z and y for my sanity
        return Snitch(world=row[0], x=row[1], z=row[2], y=row[3],
            group_name=row[4], type=row[5], name=row[6], dormant_ts=row[7],
            cull_ts=row[8], first_seen_ts=row[9], last_seen_ts=row[10], created_ts=row[11],
            created_by_uuid=row[12], renamed_ts=row[13],
            renamed_by_uuid=row[14], lost_jalist_access_ts=row[15],
            broken_ts=row[16], gone_ts=row[17], tags=row[18], notes=row[19])

    def __hash__(self):
        return hash((self.world, self.x, self.y, self.z))

    def __eq__(self, other):
        return (self.x == other.x and self.y == other.y and self.z == other.z
            and self.world == other.world)

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

    def __hash__(self):
        return hash((self.username))

    def __eq__(self, other):
        return self.username == other.username

def parse_events(path):
    events = []

    with open(path, encoding="utf8") as f:
        raw_events = f.readlines()

    for raw_event in raw_events:
        try:
            # assume events have been copy-pasted from discord and
            # so don't have markdown
            event = Event.parse(raw_event, markdown=False)
        # just ignore invalid events to facilitate copy+pasting of discord logs
        except InvalidEventException:
            continue

        events.append(event)

    return events

def parse_snitches(path):
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    rows = cur.execute("SELECT * FROM snitches_v2")
    return [Snitch.from_snitchmod(row) for row in rows]

def create_users(events):
    users = []
    usernames = {event.username for event in events}
    for i, username in enumerate(usernames):
        color = QColor().fromHslF(i / len(usernames), 0.75, 0.5)
        user = User(username, color)
        users.append(user)

    return users

def snitches_from_events(events):
    snitches = set()
    for event in events:
        # kira events don't display the world/dimension, so just assume it
        # happened in the overworld. This WILL get us into trouble when we parse
        # nether snitch events, but there's no way to differentiate, so this is
        # the best we can do.
        snitch = Snitch("world", event.x, event.y, event.z,
            event.namelayer_group, None, event.snitch_name, None, None, None,
            None, None, None, None, None, None, None, None, None, None)
        snitches.add(snitch)
    return snitches

class Snitchvis(QMainWindow):
    def __init__(self, snitches, events, users, *,
        speeds=[0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 3.0, 5.0, 10.0],
        start_speed=1, show_all_snitches=False, event_mode="square"
    ):
        super().__init__()

        self.setAutoFillBackground(True)
        self.setWindowTitle("SnitchVis")

        self.interface = Interface(snitches, events, users, speeds, start_speed,
            show_all_snitches, event_mode)
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
    def __init__(self, snitches, events, users, *,
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
            speeds=self.speeds, start_speed=self.start_speed,
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

# in ms (relative to real time), shortest possible video length
MINIMUM_VIDEO_DURATION = 500
# in ms (relative to real time)
MINIMUM_EVENT_FADE = 1500

class SnitchVisRecord:
    def __init__(self, snitches, events, users, size, framerate, duration_rt,
        show_all_snitches, event_fade_percentage, event_mode, output_file):
        self.snitches = snitches
        self.events = events
        self.users = users
        self.size = size
        # frames per second
        self.framerate = framerate
        self.show_all_snitches = show_all_snitches
        self.event_mode = event_mode
        self.output_file = output_file

        # our events cover `duration` ms (in game time), and we need to
        # compress that into `duration_rt` ms (in real time) at
        # `framerate` fps. we have `framerate * duration_rt / 1000` frames
        # to work with, and each frame needs to take
        # `duration / num_frames` seconds.

        # duration_rt is in ms (relative to real time)

        max_t = max(e.t for e in self.events)
        min_t = min(e.t for e in self.events)
        # in ms (relative to game time). convert to ms from datetime
        duration = (max_t - min_t).total_seconds() * 1000

        # realtime duration can't be longer than ingame duration, or we'd have
        # to elongate the video instead of compressing it.
        # also, neither realtime duration nor ingame duration can be smaller
        # than MINIMUM_VIDEO_DURATION, to avoid divide by zero errors.
        duration = max(MINIMUM_VIDEO_DURATION, duration)
        duration_rt = np.clip(MINIMUM_VIDEO_DURATION, duration_rt, duration)

        self.num_frames = int((duration_rt / 1000) * self.framerate)
        # in ms (relative to game time)
        self.frame_duration = duration / self.num_frames
        # in ms (relative to real time)
        self.frame_duration_rt = duration_rt / self.num_frames
        # in ms (relative to game time)
        self.event_fade = duration * (event_fade_percentage / 100)
        # event fade can't be smaller than MINIMUM_EVENT_FADE
        # convert real time (units of MINIMUM_EVENT_FADE) to in game time
        # (units of event_fade)
        min_event_fade_gametime = MINIMUM_EVENT_FADE * (duration / duration_rt)
        self.event_fade = max(self.event_fade, min_event_fade_gametime)

        # we want to add a little bit of padding farmes beyond when the last
        # frame occurs, so that the last event doesn't appear to get cut off.
        # This also allows the fade duration on the event to finish playing out.
        # We'll add 10% of the video duration or 1 second, whichever is shorter.
        # in ms (relative to real time)
        padding_t = min(0.1 * duration_rt, 1000)
        self.num_frames += int(padding_t / self.frame_duration_rt)

    @profile
    def render(self):
        renderer = FrameRenderer(None, self.snitches, self.events, self.users,
            self.show_all_snitches, self.event_mode)
        renderer.event_fade = self.event_fade
        renderer.draw_coordinates = False

        image = QImage(self.size, self.size, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.black)
        renderer.paint_object = image
        renderer.render(drawing_base_frame=True)
        renderer.base_frame = image
        # world_pixmap takes up tons of memory and we only need it so we can
        # crop the frame for the base frame, so free it immediately after
        renderer.world_pixmap = None


        # https://stackoverflow.com/a/13298538
        # -y overwrites output file if exists
        # -r specifies framerate (frames per second)
        crf = "23" # 23 is default
        preset = "medium" # medium is default
        codec = "mjpeg"
        args = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel", "error",
            "-f", "image2pipe",
            "-r", str(self.framerate),
            "-pix_fmt", "yuv420p",
            "-vcodec", codec,
            "-i", "-",
            "-vcodec", "libx264",
            "-preset", preset,
            "-crf", crf,
            self.output_file
        ]

        with Popen(args, stdin=PIPE) as p:
            for i in range(self.num_frames):
                print(f"rendering image {i} / {self.num_frames}")
                image = QImage(self.size, self.size, QImage.Format.Format_RGB32)
                image.fill(Qt.GlobalColor.black)

                renderer.paint_object = image
                renderer.t = int(i * self.frame_duration)
                renderer.render()

                buffer = QBuffer()
                print(f"saving image {i} to buffer")
                image.save(buffer, "jpeg", quality=100)
                p.stdin.write(buffer.data())

            p.stdin.close()
            print("waiting for ffmpeg to finish")
            p.wait()

        print("done rendering")
