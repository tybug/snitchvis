from dataclasses import dataclass
import re
from datetime import datetime, timezone
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

    # substitutions from https://github.com/HubSpot/jinjava/blob/28b13206
    # be9bfc5ef8ba96a5faff471c7f388dd8/src/main/java/com/hubspot/jinjava/
    # objects/date/StrftimeFormatter.java
    MAPPING = {
        "EEE": "a",
        "EEEE": "A",
        "MMM": "b",
        "MMMM": "B",
        "EEE MMM dd HH:mm:ss yyyy": "c",
        "dd": "d",
        "d": "e",
        "SSSSSS": "f",
        "HH": "H",
        "hh": "I",
        "DDD": "j",
        "H": "k",
        "h": "l",
        "MM": "m",
        "mm": "M",
        "a": "p",
        "ss": "S",
        "ww": "U",
        "e": "w",
        "MM/dd/yy": "x",
        "HH:mm:ss": "X",
        "yy": "y",
        "yyyy": "Y",
        "Z": "z",
        "z": "Z"
    }
    # adapted from https://stackoverflow.com/a/15448887. Could probably be
    # made more readable (is the len sort really necessary?)
    MAPPING_PATTERN = re.compile(
        "|".join(
            [re.escape(k) for k in sorted(MAPPING, key=len, reverse=True)]
        )
    )

    @classmethod
    def parse(cls, raw_event, snitch_f, enter_f, login_f, logout_f, time_f):
        pattern = re.escape(snitch_f)
        # replace formats with named groups, as groups could appear in any order
        # (or any number of times) in the input string
        pattern = pattern.replace("%TIME%", "(?P<time>.*)")
        pattern = pattern.replace("%GROUP%", "(?P<group>.*)")
        pattern = pattern.replace("%PLAYER%", "(?P<username>.*)")
        pattern = pattern.replace("%ACTION%", "(?P<action>.*)")
        pattern = pattern.replace("%SNITCH%", "(?P<snitch_name>.*)")
        pattern = pattern.replace("%X%", "(?P<x>.*)")
        pattern = pattern.replace("%Y%", "(?P<y>.*)")
        pattern = pattern.replace("%Z%", "(?P<z>.*)")

        # ping is annoying to handle, for a combination of two reasons:
        #
        # * discord strips trailing whitespace
        # * ping is optional, proceeded by a space in the default config (but
        #   not necessarily in all configs) and is at the end of the string in
        #   the default config (but not necessarily all configs)
        #
        # We'll handle this with a special case - if %PING% is at the end of the
        # string *and* is preceeded by a space, we'll return a regex which makes
        # the space optional. Otherwise we'll return the normal regex.
        # I'm not confident this covers 100% of cases, and in fact I highly
        # doubt it covers the case of multiple %PING% formats in a single
        # message. But that is an edge case of an edge case, so I don't care to
        # handle it right now.

        if pattern.endswith(" %PING%"):
            pattern = pattern.replace("\\ %PING%", "\w*(?P<ping>.*)")
        else:
            pattern = pattern.replace("%PING%", "(?P<ping>.*)")
        result = re.match(pattern, raw_event)

        if not result:
            raise InvalidEventException()

        time_str = result.group("time")
        nl_group = result.group("group")
        username = result.group("username")
        snitch_name = result.group("snitch_name")
        x = int(result.group("x"))
        y = int(result.group("y"))
        z = int(result.group("z"))

        time_f = cls.java_strftime_to_python(time_f)

        try:
            time = datetime.strptime(time_str, time_f)
        except Exception as e:
            raise InvalidEventException(f"invalid datetime: {e}. Got "
                f"{time_str}, matching against format {time_f}")

        if "action" not in result.groupdict():
            # default to assuming it's a ping if there's no %ACTION% group in
            # the kira format (which should happen only for very weirdly set up
            # kira formats)
            EventClass = Ping
        else:
            action = result.group("action")
            if action == enter_f:
                EventClass = Ping
            elif action == logout_f:
                EventClass = Logout
            elif action == login_f:
                EventClass = Login
            else:
                raise InvalidEventException("Could not determine event type")
        # minecraft uses y as height, to preserve my sanity we're going to swap
        # and use z as height
        return EventClass(username, snitch_name, nl_group, x, z, y, time)

    @classmethod
    def java_strftime_to_python(cls, time_format):
        return cls.MAPPING_PATTERN.sub(
            lambda match: "%" + cls.MAPPING[match.group(0)], time_format
        )

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

def parse_events(path, snitch="`[%TIME%]` `[%GROUP%]` **%PLAYER%** %ACTION% "
    "at %SNITCH% (%X%,%Y%,%Z%) %PING%", enter="is", login="logged in",
    logout="logged out", time="HH:mm:ss"
):
    events = []

    with open(path, encoding="utf8") as f:
        raw_events = f.readlines()

    for raw_event in raw_events:
        try:
            event = Event.parse(raw_event, snitch, enter, login, logout, time)
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

@dataclass(kw_only=True)
class Config:
    snitches: list[Snitch]
    users: list[User]
    events: list[Event]
    show_all_snitches: bool = False
    mode: str = "box"
    heatmap_percentage: int = 20
    heatmap_scale: str = "linear"
    # in ms, relative to in game time
    event_fade: int = 5 * 60 * 1000
    # list of exactly four elements: [x1, y1, x2, y2]. Specifies the bounds of
    # the viewport and overrides automatic bounds calculation.
    bounds: list[int] = None
    draw_coordinates = True
    draw_time_span = True

class Snitchvis(QMainWindow):
    def __init__(self, config,
        speeds=[0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 3.0, 5.0, 10.0],
        start_speed=1
    ):
        super().__init__()

        self.setAutoFillBackground(True)
        self.setWindowTitle("SnitchVis")

        self.interface = Interface(speeds, start_speed, config)
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
    def __init__(self, config,
        speeds=[0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 3.0, 5.0, 10.0],
        start_speed=1
    ):
        super().__init__([])
        self.setStyle("Fusion")
        self.setApplicationName("Circlevis")

        self.visualizer = None
        self.config = config
        self.speeds = speeds
        self.start_speed = start_speed

    def exec(self):
        """
        Displays the visualizer and enters into the event loop, which will block
        the calling thread.
        """
        self.set_palette()
        # we can't create this in ``__init__`` because we can't instantiate a
        # ``QWidget`` before a ``QApplication``, so delay until here, which is
        # all it's necessary for.
        self.visualizer = Snitchvis(self.config, self.speeds, self.start_speed)
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
MINIMUM_EVENT_FADE = 500

class SnitchVisRecord:
    def __init__(self, duration_rt, size, fps, event_fade, output_file, config):
        config.draw_coordinates = False

        # duration_rt is in ms (relative to real time)
        self.fps = fps
        self.size = size
        self.output_file = output_file
        # rely on frame renderer to do complicated event filtering computations
        # for us before retrieving the event start and end td
        self.renderer = FrameRenderer(None, config)


        # our events cover `duration` ms (in game time), and we need to
        # compress that into `duration_rt` ms (in real time) at
        # `framerate` fps. we have `framerate * duration_rt / 1000` frames
        # to work with, and each frame needs to take
        # `duration / num_frames` seconds.

        start = self.renderer.event_start_td
        end = self.renderer.event_end_td

        # after event filtering, there could end up being no events. show the
        # shortest video possible in that case
        if not (start and end):
            duration = MINIMUM_VIDEO_DURATION
        else:
            # in ms (relative to game time)
            duration = (end - start).total_seconds() * 1000

        # realtime duration can't be longer than ingame duration, or we'd have
        # to elongate the video instead of compressing it.
        # also, neither realtime duration nor ingame duration can be smaller
        # than MINIMUM_VIDEO_DURATION, to avoid divide by zero errors.
        duration = max(MINIMUM_VIDEO_DURATION, duration)
        duration_rt = np.clip(MINIMUM_VIDEO_DURATION, duration_rt, duration)

        self.num_frames = int((duration_rt / 1000) * self.fps)
        # in ms (relative to game time)
        self.frame_duration = duration / self.num_frames
        # in ms (relative to real time)
        self.frame_duration_rt = duration_rt / self.num_frames
        # in ms (relative to real time)
        # can't be smaller than MINIMUM_EVENT_FADE
        event_fade = max(event_fade, MINIMUM_EVENT_FADE)
        # convert to in-game time
        event_fade *= (duration / duration_rt)

        # we want to add a little bit of padding farmes beyond when the last
        # frame occurs, so that the last event doesn't appear to get cut off.
        # This also allows the fade duration on the event to finish playing out.
        # We'll add 10% of the video duration or 1 second, whichever is shorter.
        # in ms (relative to real time)
        padding_t = min(0.1 * duration_rt, 1000)
        self.num_frames += int(padding_t / self.frame_duration_rt)

        # update config with our event fade (defaults to 5 in-game minutes
        # otherwise)
        self.renderer.event_fade = event_fade

    @profile
    def render(self):
        image = QImage(self.size, self.size, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.black)
        self.renderer.paint_object = image
        self.renderer.render(drawing_base_frame=True)
        self.renderer.base_frame = image

        # https://stackoverflow.com/a/13298538
        # -y overwrites output file if exists
        # -r specifies framerate (frames per second)
        crf = "29" # 23 is default
        preset = "medium" # medium is default
        codec = "mjpeg"
        args = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel", "error",
            "-f", "image2pipe",
            "-r", str(self.fps),
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

                self.renderer.paint_object = image
                self.renderer.t = int(i * self.frame_duration)
                self.renderer.render()

                buffer = QBuffer()
                print(f"saving image {i} to buffer")
                image.save(buffer, "jpeg", quality=100)
                p.stdin.write(buffer.data())

            p.stdin.close()
            print("waiting for ffmpeg to finish")
            p.wait()

        print("done rendering")

# render a single image to disk, instead of a video
class SnitchVisImage:
    def __init__(self, output_file, config):
        # 10 in game minutes
        config.event_fade = 10 * 60 * 1000
        config.draw_time_span = False
        config.draw_coordinates = False

        self.output_file = output_file
        self.renderer = FrameRenderer(None, config)

        # sometimes we don't want to visualize any events. In this case, it
        # doesn't actually matter what we set min_t to; the same result will be
        # rendered. We just want to avoid an exception when taking the min of an
        # empty collection.
        self.min_t = self.renderer.event_start_td
        if not self.min_t:
            # self.min_t = 0 would work too, but let's try and keep the renderer
            # time close to zero. has less of a chance of breaking things or
            # causing performance issues in the future
            self.min_t = datetime.now(timezone.utc)

    def render(self):
        image = QImage(1000, 1000, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.black)
        self.renderer.paint_object = image

        # set the renderer time properly so the event actually fades out.
        # We want to set the renderer time an equivalent time in the future to
        # how far past the first event we are. If we're rendering 10 minutes
        # past the first event, we want to set t to 10 minutes past the first
        # event. If we're rendering right at the first event, we want to set t
        # to 0.
        self.renderer.t = (datetime.now(timezone.utc) - self.min_t).total_seconds() * 1000
        self.renderer.render()

        image.save(self.output_file, "jpeg", quality=100)
