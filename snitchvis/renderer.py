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
PEN_RED = QPen(QColor(219, 16, 9))

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

GAMEPLAY_PADDING_WIDTH = 20
GAMEPLAY_PADDING_HEIGHT = 20
GAMEPLAY_WIDTH = 600
GAMEPLAY_HEIGHT = 450


class Renderer(QFrame):
    update_time_signal = pyqtSignal(int)
    pause_signal = pyqtSignal()
    loaded_signal = pyqtSignal()

    def __init__(self, snitches, events, start_speed, show_all_snitches):
        super().__init__()
        self.setMinimumSize(GAMEPLAY_WIDTH + GAMEPLAY_PADDING_WIDTH * 2,
            GAMEPLAY_HEIGHT + GAMEPLAY_PADDING_HEIGHT * 2)

        self.snitches = snitches
        self.events = events

        # figure out a bounding box for our events.
        # if we want to show all our snitches instead of all our events, bound
        # to the snitches instead.
        bounding_events = self.snitches if show_all_snitches else self.events
        # first, we'll find the extremities of the events.
        self.max_x = max(e.x for e in bounding_events)
        self.min_x = min(e.x for e in bounding_events)
        self.max_y = max(e.y for e in bounding_events)
        self.min_y = min(e.y for e in bounding_events)
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

        self.painter = QPainter()

        self.setMouseTracking(True)

        # whether the previous frame was a loading frame or not, used to
        # determine when we came out of a loading state
        self.previously_loading = False

        self.playback_start = 0
        self.playback_end = max(event.t for event in events)

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


    def scaled_x(self, x):
        # * snitch cordinates: relative to the civmc map. eg -6750, 2300
        # * snitch bounding box coordinates: relative to the bounding box of the
        #   snitches we've been passed, which is the smallest square which
        #   contains all the passed snitches.
        # * view coordinates: relative to the full renderer widget, so 0,0 is
        #   just below the x button of the window
        # * draw coordinates: relative to the draw area of the renderer
        #   widget, which is the sub area of the view area after padding by
        #   GAMEPLAY_PADDING_HEIGHT and GAMEPLAY_PADDING_WIDTH. Will always be
        #   a square.

        # right now we have the snitch coordiantes. We want view coordinates.
        # First, we'll convert to draw coordinates, then pad to get view
        # coordinates.

        # Figure out the width of the draw area so we can scale our snitch
        # coordinates accordingly.
        draw_width = self.width() - 2 * GAMEPLAY_PADDING_WIDTH
        draw_height = self.height() - 2 * GAMEPLAY_PADDING_HEIGHT
        # draw area is always a square, so just pick the least of the two
        draw_size = min(draw_width, draw_height)
        # how far in to the snitch bounding box are we?
        snitch_bounding_box_ratio = (x - self.min_x) / (self.max_x - self.min_x)
        # multiply that by the width of the draw area to get our draw area
        # coordinates
        draw_area_coords = draw_size * snitch_bounding_box_ratio
        # pad by GAMEPLAY_PADDING_WIDTH to get the view coordinates
        draw_area_coords += GAMEPLAY_PADDING_WIDTH
        # we actually need to do a bit more than this...if the renderer is wider
        # than it is tall, we'll have extra padding that we didn't account for.
        # figure out how much wider than tall we are (if at all) and pad by half
        # that amount to center us.
        draw_area_coords += max(self.width() - self.height(), 0) / 2
        return draw_area_coords

    def scaled_y(self, y):
        draw_width = self.width() - 2 * GAMEPLAY_PADDING_WIDTH
        draw_height = self.height() - 2 * GAMEPLAY_PADDING_HEIGHT
        draw_size = min(draw_width, draw_height)
        # how far in to the snitch bounding box are we?
        snitch_bounding_box_ratio = (y - self.min_y) / (self.max_y - self.min_y)
        # multiply that by the width of the draw area to get our draw area
        # coordinates
        draw_area_coords = draw_size * snitch_bounding_box_ratio
        # pad by GAMEPLAY_PADDING_HEIGHT to get the view coordinates
        draw_area_coords += GAMEPLAY_PADDING_HEIGHT
        # add additional padding if we're taller than we are wide
        draw_area_coords += max(self.height() - self.width(), 0) / 2
        return draw_area_coords


    def scaled_point(self, x, y):
        return QPointF(self.scaled_x(x), self.scaled_y(y))

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

    def next_frame(self):
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

        self.update_time_signal.emit(int(current_time))
        self.update()

    def paintEvent(self, _event):
        """
        Called whenever self.update() is called
        """
        self.painter.begin(self)
        self.painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # time elapsed
        self.paint_time()
        # snitches
        self.paint_snitches()
        # events
        self.paint_events()

        self.painter.end()

    def paint_time(self):
        # our current y coordinate for drawing info. Modified throughout this
        # function
        y = 15

        PEN_WHITE.setWidth(1)
        self.painter.setPen(PEN_WHITE)
        self.painter.setOpacity(1)
        ms = round(self.clock.get_time())
        text = f"{ms}"
        self.painter.drawText(5, y, text)
        # we don't use a monospaced font, so our ms text may vary by as much as
        # 10 pixels in width (possibly more, haven't checked rigorously). If
        # we just drew our minute:seconds text directly after it, the position
        # of that text would constantly flicker left and right, since the ms
        # text (and thus its width) changes every single frame. To fix this,
        # only increment widths in multiples of 10. (This will not fix the issue
        # if the text width happens to hover exactly around a multiple of 10,
        # but there's not much to be done in that case).
        text_width = self.painter.boundingRect(5, y, 0, 0, 0, text).width()
        if text_width < 50:
            x = 50
        elif text_width < 60:
            x = 60
        elif text_width < 70:
            x = 70
        elif text_width < 80:
            x = 80
        else:
            # something crazy is going on, give up and just use text_width
            x = text_width

        # now some dirty code to deal with negattive times
        minutes = int(ms / (1000 * 60))
        seconds = ms // 1000
        seconds_negative = seconds < 0
        # pytohn modulo returns positive even when ``seconds_total`` is negative
        seconds = seconds % 60
        if seconds_negative:
            # ``seconds`` can be 0 and 59 but not 60, so use 59 instead of 60
            seconds = 59 - seconds
        sign = ""
        if minutes < 0 or seconds_negative:
            sign = "-"
            minutes = abs(minutes)
            seconds = abs(seconds)

        self.painter.drawText(5 + 4 + x, y,
            f"ms ({sign}{minutes:01}:{seconds:02})")

    def paint_snitches(self):
        PEN_BLUE.setWidth(1)
        self.painter.setPen(PEN_BLUE)
        self.painter.setOpacity(1)

        # snitch fields
        # TODO opacity
        for snitch in self.snitches:
            self.draw_rectangle(snitch.x - 11, snitch.y - 11,
                snitch.x + 12, snitch.y + 12, fill_with=BRUSH_BLUE)

        # snitches
        for snitch in self.snitches:
            self.draw_rectangle(snitch.x, snitch.y, snitch.x + 1, snitch.y + 1,
                fill_with=BRUSH_WHITE)

    def paint_events(self):
        current_time = self.clock.get_time()
        for event1, event2 in zip(self.events, self.events[1:]):
            if not current_time - 1000000 <= event2.t <= current_time:
                continue
            self.draw_line(event1.x, event1.y, event2.x, event2.y, 1, PEN_RED, 2)

    def draw_rectangle(self, start_x, start_y, end_x, end_y, *, fill_with=None):
        start = self.scaled_point(start_x, start_y)
        end = self.scaled_point(end_x, end_y)
        rect = QRectF(start, end)
        if not fill_with:
            self.painter.drawRect(rect)
            return
        self.painter.fillRect(rect, fill_with)

    def draw_line(self, start_x, start_y, end_x, end_y, alpha, pen, width):
        pen.setWidth(width)
        self.painter.setPen(pen)
        self.painter.setOpacity(alpha)
        self.painter.drawLine(self.scaled_point(start_x, start_y),
            self.scaled_point(end_x, end_y))

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
        self.painter.drawText(x, y, "Loading...")
        progress = 0
        self.draw_progressbar(progress)

    def next_event(self, reverse=False):
        current_time = self.clock.get_time()
        event_times = [e.t for e in self.events]
        # pick the most extreme event in the case of duplicate events
        side = "left" if reverse else "right"
        index = np.searchsorted(event_times, current_time, side)

        if reverse:
            index -= 1

        # prevent out of bounds errors
        index = np.clip(index, 0, len(self.events) - 1)
        event = self.events[index]
        self.seek_to(event.t)

    def seek_to(self, position):
        self.clock.time_counter = position
        if self.paused:
            self.next_frame()

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
