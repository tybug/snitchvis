from dataclasses import dataclass
from datetime import timedelta

import numpy as np
from PyQt6.QtGui import QColor, QPalette, QPainter, QCursor
from PyQt6.QtWidgets import QFrame
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QPointF, QRectF, QRect

from snitchvis.clock import Timer

WIDTH_LINE = 1
WIDTH_LINE_RAW_VIEW = 2
WIDTH_CROSS = 2
LENGTH_CROSS = 6

# white
TEXT_COLOR = QColor(200, 200, 200)
# 23x23 square, light blue
SNITCH_FIELD_COLOR = QColor(93, 183, 223)
# actual snitch block, white
SNITCH_BLOCK_COLOR = QColor(200, 200, 200)

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

        # normalize all event times to the earliest event, and convert to ms
        self.event_start_t = min(event.t for event in events)
        self.event_end_t = max(event.t for event in events)
        for event in events:
            event.t = int((event.t - self.event_start_t).total_seconds() * 1000)

        # get all unique usernames
        usernames = {event.username for event in events}
        self.users = []
        for i, username in enumerate(usernames):
            color = QColor().fromHslF(i / len(usernames), 0.75, 0.5)
            user = User(username, color)
            self.users.append(user)
        # hash by username for convenience
        self.users_by_username = {user.username: user for user in self.users}


        self.snitches = snitches
        self.events = sorted(events, key = lambda event: event.t)
        self.current_mouse_x = 0
        self.current_mouse_y = 0
        # 5 minutes in ms
        self.snitch_event_limit = 5 * 60 * 1000

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
        self.paint_info()
        # snitches
        self.paint_snitches()

        self.painter.end()

    def paint_info(self):
        # our current y coordinate for drawing info. Modified throughout this
        # function
        y = 15
        # x offset from edge of screen
        x_offset = 5


        start = self.event_start_t.strftime('%m/%d/%Y %H:%M')
        # if the snitch log only covers a single day, don't show mm/dd/yyyy
        # twice
        if self.event_start_t.date() == self.event_end_t.date():
            end = self.event_end_t.strftime('%H:%M')
        # different days, show full date for each
        else:
            end = self.event_end_t.strftime('%m/%d/%Y %H:%M')
        self.draw_text(x_offset, y, f"Snitch Log {start} - {end}")

        # draw current time
        y += 18
        timedelta_in = timedelta(milliseconds=int(self.clock.get_time()))
        current_t = self.event_start_t + timedelta_in
        self.draw_text(x_offset, y, current_t.strftime('%m/%d/%Y %H:%M:%S'))

        # draw all usernames with corresponding colors
        for user in self.users:
            y += 16

            alpha = 1 if user.enabled else 0.4
            start_x = 5
            start_y = y - 9
            self.draw_rectangle(start_x, start_y, start_x + 10, start_y + 10,
                color=user.color, alpha=alpha, scaled=False)

            text = user.username
            self.draw_text(x_offset + 14, y, text, alpha=alpha)

            # bounding rects require that we have a pen set, or else it will
            # (correctly) return QRect(0, 0, 0, 0), as the text won't actually
            # be visible.
            self.painter.setPen(TEXT_COLOR)
            info_pos = self.painter.boundingRect(5, y - 9, 0, 0, 0, text)
            self.painter.setPen(Qt.PenStyle.NoPen)
            rect = QRect(info_pos.x(), info_pos.y(), info_pos.width(),
                info_pos.height())
            # some manual adjustments, not sure why these are necessary
            rect.setHeight(rect.height() - 3)
            rect.setWidth(rect.width() + 17)
            user.info_pos_rect = rect

        # draw current mouse coordinates
        y += 16
        self.draw_text(x_offset, y,
            f"{int(self.current_mouse_x)}, {int(self.current_mouse_y)}")

    def paint_snitches(self):
        current_time = self.clock.get_time()

        # snitch fields
        for snitch in self.snitches:
            self.draw_rectangle(snitch.x - 11, snitch.y - 11,
                snitch.x + 12, snitch.y + 12, color=SNITCH_FIELD_COLOR,
                alpha=0.23)
        for snitch in self.snitches:
            color = None
            alpha = None

            for event in snitch.events:
                if not current_time - self.snitch_event_limit <= event.t <= current_time:
                    continue
                user = self.users_by_username[event.username]
                # don't draw events from disabled users
                if not user.enabled:
                    continue
                color = user.color
                alpha = (1 - (current_time - event.t) / self.snitch_event_limit)

            if not (color and alpha):
                continue
            self.draw_rectangle(snitch.x - 11, snitch.y - 11, snitch.x + 12,
                snitch.y + 12, color=color, alpha=alpha)

        for snitch in self.snitches:
            self.draw_rectangle(snitch.x, snitch.y, snitch.x + 1, snitch.y + 1,
                color=SNITCH_BLOCK_COLOR)

    def draw_rectangle(self, start_x, start_y, end_x, end_y, *, color, alpha=1,
        scaled=True
    ):
        color = QColor(color.red(), color.green(), color.blue())
        self.painter.setPen(Qt.PenStyle.NoPen)
        self.painter.setOpacity(alpha)
        self.painter.setBrush(color)

        if scaled:
            start = self.scaled_point(start_x, start_y)
            end = self.scaled_point(end_x, end_y)
        else:
            start = QPointF(start_x, start_y)
            end = QPointF(end_x, end_y)
        rect = QRectF(start, end)
        self.painter.drawRect(rect)

    def draw_line(self, start_x, start_y, end_x, end_y, alpha, pen, width):
        pen.setWidth(width)
        self.painter.setPen(pen)
        self.painter.setOpacity(alpha)
        self.painter.drawLine(self.scaled_point(start_x, start_y),
            self.scaled_point(end_x, end_y))

    def draw_text(self, x, y, text, alpha=1):
        pen = self.painter.pen()
        self.painter.setPen(TEXT_COLOR)
        self.painter.setOpacity(alpha)
        self.painter.drawText(x, y, text)
        self.painter.setPen(pen)

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

    def mouseMoveEvent(self, event):
        x = event.pos().x()
        y = event.pos().y()
        # convert local screen coordinates (where 0,0 is the upper left corner)
        # to in-game coordinates.

        # how wide is the snitch bounding box in pixels?
        draw_width = self.width() - 2 * GAMEPLAY_PADDING_WIDTH
        draw_height = self.height() - 2 * GAMEPLAY_PADDING_HEIGHT
        draw_size = min(draw_width, draw_height)

        x -= GAMEPLAY_PADDING_WIDTH + max(self.width() - self.height(), 0) / 2
        y -= GAMEPLAY_PADDING_HEIGHT + max(self.height() - self.width(), 0) / 2

        # how far in to the snitch bounding box are we?
        ratio_x = x / draw_size
        ratio_y = y / draw_size

        # bounding box should always be a square
        assert self.max_x - self.min_x == self.max_y - self.min_y
        self.current_mouse_x = self.min_x + ratio_x * (self.max_x - self.min_x)
        self.current_mouse_y = self.min_y + ratio_y * (self.max_y - self.min_y)

        cursor = QCursor(Qt.CursorShape.ArrowCursor)
        for user in self.users:
            if user.info_pos_rect.contains(event.pos()):
                cursor = QCursor(Qt.CursorShape.PointingHandCursor)
        self.setCursor(cursor)

        # update in case we're paused
        self.update()

        return super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        for user in self.users:
            rect = user.info_pos_rect
            if not rect.contains(event.pos()):
                continue
            user.enabled = not user.enabled

        # in case this mouse press enabled/disabled any players and we're
        # paused, update once
        self.update()
        return super().mousePressEvent(event)

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

@dataclass
class User:
    username: str
    color: QColor
    # init with an empty qrect, we'll set the actual info pos later
    info_pos_rect: QRect = QRect(0, 0, 0, 0)
    enabled: bool = True
