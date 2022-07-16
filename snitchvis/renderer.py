
import numpy as np
from PyQt6.QtGui import QColor, QPalette, QCursor
from PyQt6.QtWidgets import QFrame
from PyQt6.QtCore import Qt, pyqtSignal, QTimer

from snitchvis.clock import Timer
from snitchvis.frame_renderer import FrameRenderer

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

    def __init__(self, snitches, events, users, start_speed, show_all_snitches,
        event_start_td):
        super().__init__()
        self.setMinimumSize(GAMEPLAY_WIDTH + GAMEPLAY_PADDING_WIDTH * 2,
            GAMEPLAY_HEIGHT + GAMEPLAY_PADDING_HEIGHT * 2)

        self.users = users
        # hash by username for convenience
        self.users_by_username = {user.username: user for user in self.users}

        self.events = events

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

        self.frame_renderer = FrameRenderer(self, snitches, events, users,
            show_all_snitches, event_start_td)

        # black background
        pal = QPalette()
        pal.setColor(QPalette.ColorGroup.Normal,
            QPalette.ColorRole.Window, Qt.GlobalColor.black)
        # also set when app is in background
        pal.setColor(QPalette.ColorGroup.Inactive,
            QPalette.ColorRole.Window, Qt.GlobalColor.black)
        self.setAutoFillBackground(True)
        self.setPalette(pal)

        self.next_frame()

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

        paint_width = self.frame_renderer.paint_width()
        paint_height = self.frame_renderer.paint_height()
        # how wide is the snitch bounding box in pixels?
        draw_width = paint_width - 2 * GAMEPLAY_PADDING_WIDTH
        draw_height = paint_height - 2 * GAMEPLAY_PADDING_HEIGHT
        draw_size = min(draw_width, draw_height)

        x -= GAMEPLAY_PADDING_WIDTH + max(paint_width - paint_height, 0) / 2
        y -= GAMEPLAY_PADDING_HEIGHT + max(paint_height - paint_width, 0) / 2

        # how far in to the snitch bounding box are we?
        ratio_x = x / draw_size
        ratio_y = y / draw_size

        max_x = self.frame_renderer.max_x
        min_x = self.frame_renderer.min_x
        max_y = self.frame_renderer.max_y
        min_y = self.frame_renderer.min_y
        # bounding box should always be a square
        assert max_x - min_x == max_y - min_y
        mouse_x = min_x + ratio_x * (max_x - min_x)
        mouse_y = min_y + ratio_y * (max_y - min_y)
        self.frame_renderer.current_mouse_x = mouse_x
        self.frame_renderer.current_mouse_y = mouse_y

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

    def paintEvent(self, _event):
        self.frame_renderer.paint_object = self
        self.frame_renderer.t = int(self.clock.get_time())
        self.frame_renderer.render()
