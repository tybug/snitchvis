from dataclasses import dataclass

import numpy as np
from PyQt6.QtGui import QBrush, QPen, QColor, QPalette, QPainter, QPainterPath
from PyQt6.QtWidgets import QFrame
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QPointF, QRectF, QRect

from snitchvis.clock import Timer

WIDTH_LINE = 1
WIDTH_LINE_RAW_VIEW = 2
WIDTH_CROSS = 2
LENGTH_CROSS = 6

PEN_WHITE = QPen(QColor(200, 200, 200))
PEN_GRAY = QPen(QColor(75, 75, 75))
PEN_GREY_INACTIVE = QPen(QColor(133, 125, 125))
PEN_HIGHLIGHT = QPen(QColor(230, 212, 92))
PEN_BLANK = QPen(QColor(0, 0, 0, 0))
PEN_RED_TINT = QPen(QColor(200, 150, 150))

PEN_BLUE = QPen(QColor(93, 183, 223))
PEN_GREEN = QPen(QColor(127, 221, 71))
PEN_YELLOW = QPen(QColor(211, 175, 90))

BRUSH_BLUE = QBrush(QColor(93, 183, 223))
BRUSH_GREEN = QBrush(QColor(127, 221, 71))
BRUSH_YELLOW = QBrush(QColor(211, 175, 90))

BRUSH_WHITE = QBrush(QColor(200, 200, 200))
BRUSH_GRAY = QBrush(QColor(100, 100, 100))
BRUSH_DARKGRAY = QBrush(QColor(10, 10, 10))
BRUSH_BLANK = QBrush(QColor(0, 0, 0, 0))

GAMEPLAY_PADDING_WIDTH = 50
GAMEPLAY_PADDING_HEIGHT = 60
GAMEPLAY_WIDTH = 600
GAMEPLAY_HEIGHT = 450


class Renderer(QFrame):
    update_time_signal = pyqtSignal(int)
    pause_signal = pyqtSignal()
    loaded_signal = pyqtSignal()

    def __init__(self, snitches, pings, start_speed):
        super().__init__()
        self.setMinimumSize(GAMEPLAY_WIDTH + GAMEPLAY_PADDING_WIDTH * 2,
            GAMEPLAY_HEIGHT + GAMEPLAY_PADDING_HEIGHT * 2)

        self.snitches = snitches
        self.pings = pings

        # figure out a bounding box for our snitches.
        # first, we'll find the extremities of the snitches.
        self.max_x = max(s.x for s in self.snitches)
        self.min_x = min(s.x for s in self.snitches)
        self.max_y = max(s.y for s in self.snitches)
        self.min_y = min(s.y for s in self.snitches)
        # this is almost certainly a rectangle, so we'll pad it out to be a
        # square, adding padding along the shorter axis.
        x_dist = self.max_x - self.min_x
        y_dist = self.max_y - self.min_y
        dist_diff = abs(x_dist - y_dist)

        # pad along both sides of the axis equally so the snitches are centered
        # in the square
        if x_dist < y_dist:
            self.max_x += (dist_diff / 2)
            self.min_x -= (dist_diff / 2)
        if y_dist < x_dist:
            self.max_y += (dist_diff / 2)
            self.min_y -= (dist_diff / 2)

        print(self.min_x, self.max_x, self.min_y, self.max_y)

        self.painter = QPainter()
        self.scale = 1
        self.x_offset = 0
        self.y_offset = 0

        self.setMouseTracking(True)

        # whether the previous frame was a loading frame or not, used to
        # determine when we came out of a loading state
        self.previously_loading = False

        self.playback_start = 0
        self.playback_end = max(ping.t for ping in pings)

        self.clock = Timer(start_speed, self.playback_start)
        self.paused = False
        self.play_direction = 1

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.next_frame_from_timer)
        # 62 fps (1000ms / 60frames but the result can only be a integer)
        self.timer.start(int(1000/60))

        # black background
        pal = QPalette()
        pal.setColor(QPalette.ColorGroup.Normal,
            QPalette.ColorRole.Window, Qt.GlobalColor.black)
        self.setAutoFillBackground(True)
        self.setPalette(pal)

        self.next_frame()

    def resizeEvent(self, event):
        width = event.size().width() - GAMEPLAY_PADDING_WIDTH * 2
        height = event.size().height() - GAMEPLAY_PADDING_HEIGHT * 2
        y_scale = height / GAMEPLAY_HEIGHT
        x_scale = width / GAMEPLAY_WIDTH
        if GAMEPLAY_WIDTH * y_scale > width:
            self.scale = x_scale
            self.y_offset = (height - GAMEPLAY_HEIGHT * x_scale) / 2
            self.x_offset = 0
        else:
            self.scale = y_scale
            self.y_offset = 0
            self.x_offset = (width - GAMEPLAY_WIDTH * y_scale) / 2

        print(round(x_scale, 2), round(y_scale, 2), round(self.scale, 2), round(self.x_offset, 2), round(self.y_offset, 2))

    def _x(self, position):
        return (self.x_offset + GAMEPLAY_PADDING_WIDTH +
            self.scaled_number(position))

    def _y(self, position):
        return (self.y_offset + GAMEPLAY_PADDING_HEIGHT +
            self.scaled_number(position))

    def scaled_point(self, x, y):
        return QPointF(self._x(x), self._y(y))

    def scaled_number(self, n):
        return int(n * self.scale)

    def next_frame_from_timer(self):
        """
        Has the same effect as next_frame except if paused, where it returns.
        This is to allow the back/forward buttons to advance frame by frame
        while still paused (as they connect directly to next and previous
        frame), while still pausing the automatic timer advancement.
        """
        if self.paused:
            return

        self.next_frame()

    def next_frame(self, reverse=False):
        """
        Prepares the next frame.

        If we have just set our current time to be less than what it was the
        previous time next_frame was called, pass stepping_backwards=True so
        the correct frame can be chosen when searching the frame list.
        """
        current_time = self.clock.get_time()
        # if we're at the end of the track or are at the beginning of the track
        # (and thus are reversing), pause and dont update
        if current_time > self.playback_end or current_time < self.playback_start:
            self.pause_signal.emit()
            return

        # This is the solution to the issue of stepping forward/backwards
        # getting stuck on certain frames - we can fix it for stepping forward
        # by always preferring the right side when searching our array, but when
        # stepping backwards we need to prefer the left side instead.
        side = "left" if reverse else "right"
        ping_times = [ping.t for ping in self.pings]
        new_ping_time = np.searchsorted(ping_times, current_time, side)
        # TODO reimplement this
        # for player in self.players:
        #     player.end_pos = np.searchsorted(player.t, current_time, side)
        #     # for some reason side=right and side=left differ by 1 even when
        #     # the array has no duplicates, so only account for that in the
        #     # right side case
        #     if side == "right":
        #         player.end_pos -= 1

        #     player.start_pos = 0
        #     if player.end_pos >= self.num_frames_on_screen:
        #         player.start_pos = player.end_pos - self.num_frames_on_screen

        #     # never go out of bounds
        #     if player.end_pos >= len(player.xy):
        #         player.end_pos = len(player.xy) - 1

        self.update_time_signal.emit(int(current_time))
        self.update()

    def paintEvent(self, _event):
        """
        Called whenever self.update() is called
        """
        self.painter.begin(self)
        self.painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.painter.setPen(PEN_WHITE)

        # snitches
        self.paint_snitches()

        self.painter.end()

    def paint_snitches(self):
        PEN_BLUE.setWidth(self.scaled_number(1))
        self.painter.setPen(PEN_BLUE)
        self.painter.setOpacity(1)

        for snitch in self.snitches:
            start = self.scaled_point(snitch.x - 1, snitch.y - 1)
            end = self.scaled_point(snitch.x + 1, snitch.y + 1)
            self.painter.drawRect(QRectF(start, end))

    def draw_line(self, alpha, start, end, grey_out=False):
        """
        Draws a line at the given alpha level from the start point to the end
        point.

        Arguments:
            Float alpha: The alpha level (from 0.0 to 1.0) to set the line to.
            List start: The X&Y position of the start of the line.
            List end: The X&Y position of the end of the line.
            Boolean grey_out: Whether to grey out the line or not.
        """
        if grey_out:
            prev_pen = self.painter.pen()
            PEN_GREY_INACTIVE.setWidth(self.scaled_number(WIDTH_LINE_RAW_VIEW))
            self.painter.setPen(PEN_GREY_INACTIVE)

        self.painter.setOpacity(alpha)
        self.painter.drawLine(self.scaled_point(start[0], start[1]),
            self.scaled_point(end[0], end[1]))

        if self.raw_view and grey_out:
            self.painter.setPen(prev_pen)

    def draw_progressbar(self, percentage):
        loading_bg = QPainterPath()
        loading_bar = QPainterPath()
        c = self.painter.pen().color()

        _pen = self.painter.pen()
        _pen.setWidth(5)
        _pen.setCapStyle(Qt.RoundCap)
        _pen.setJoinStyle(Qt.RoundJoin)
        _pen.setColor(QColor(c.red(), c.green(), c.blue(), 25))
        self.painter.setPen(_pen)

        loading_bg.moveTo(self.width()/2 - 75, self.height() / 2)
        loading_bg.lineTo(self.width()/2 - 75 + 150, self.height() / 2)

        loading_bar.moveTo(self.width() / 2 - 75, self.height() / 2)
        loading_bar.lineTo(self.width() / 2 - 75 + percentage * 1.5,
            self.height() / 2)

        self.painter.drawPath(loading_bg)
        _pen.setColor(QColor(c.red(), c.green(), c.blue(), 255))
        self.painter.setPen(_pen)
        self.painter.drawPath(loading_bar)

    def draw_loading_screen(self):
        x = self.width() / 2 - 75
        y = self.height() / 2 - 10
        self.painter.drawText(x, y, "Calculating Sliders, please wait...")
        # TODO progress
        progress = 0
        self.draw_progressbar(progress)

    def search_nearest_frame(self, reverse=False):
        """
        Args
            Boolean reverse: whether to search backwards or forwards through
                time
        """
        if not reverse:
            next_frames = []
            for player in self.players:
                pos = player.end_pos + 1
                # stay at the end of the replay, avoid index error
                if pos == len(player.xy):
                    pos -= 1
                next_frames.append(player.t[pos])
            # if we're only visualizing a beatmap and there's no replays, and
            # someone tries to advance or retreat frames, min() / max() will
            # crash because next_frames is empty, so avoid this.
            if not next_frames:
                return
            self.seek_to(min(next_frames))
        else:
            prev_frames = []
            for player in self.players:
                pos = player.end_pos - 1
                # stay at the beginning of the replay, don't wrap around to end
                if pos == -1:
                    pos += 1
                prev_frames.append(player.t[pos])
            if not prev_frames:
                return
            self.seek_to(max(prev_frames), reverse=True)

    def seek_to(self, position, reverse=False):
        self.clock.time_counter = position
        if self.paused:
            self.next_frame(reverse=reverse)

    def wheelEvent(self, event):
        # from the qt docs on pixelDelta: "This value is provided on platforms
        # that support high-resolution pixel-based delta values, such as macOS".
        # Since not every OS provides pixelDelta, we should use it if possible
        # but fall back to angleDelta. From my testing (sample size 1)
        # pixelDelta will have both x and y as zero if it's unsupported.
        if event.pixelDelta().x() == 0 and event.pixelDelta().y() == 0:
            # check both x and y to support users scrolling either vertically or
            # horizontally to move the timeline, just respect whichever is
            # greatest for that event.
            # this /5 is an arbitrary value to slow down scrolling to what
            # feels reasonable. TODO expose as a setting to the user ("scrolling
            # sensitivity")
            delta = max(event.angleDelta().x(), event.angleDelta().y(), key=abs) / 5
        else:
            delta = max(event.angleDelta().x(), event.angleDelta().y(), key=abs)

        self.seek_to(self.clock.time_counter + delta)

    def pause(self):
        """
        Set paused flag and pauses the clock.
        """
        self.paused = True
        self.clock.pause()

    def resume(self):
        """
        Removes paused flag and resumes the clock.
        """
        self.paused = False
        self.clock.resume()

# not sure why dataclass won't generate a hash method for us automatically,
# we're not using anything mutable, just ints
@dataclass(unsafe_hash=True)
class Rect:
    """
    A dataclass which mimics ``QRect`` and only serves as a hashable liaison of
    ``QRect``.
    """
    x: int
    y: int
    width: int
    height: int

    def toQRect(self):
        return QRect(self.x, self.y, self.width, self.height)
