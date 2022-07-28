
import numpy as np
from PyQt6.QtGui import QPalette, QCursor
from PyQt6.QtWidgets import QFrame
from PyQt6.QtCore import Qt, pyqtSignal, QTimer

from snitchvis.clock import Timer
from snitchvis.frame_renderer import FrameRenderer

GAMEPLAY_PADDING_WIDTH = 20
GAMEPLAY_PADDING_HEIGHT = 20
GAMEPLAY_WIDTH = 600
GAMEPLAY_HEIGHT = 450


class Renderer(QFrame):
    update_time_signal = pyqtSignal(int)
    pause_signal = pyqtSignal()
    loaded_signal = pyqtSignal()

    def __init__(self, snitches, events, users, start_speed, show_all_snitches,
        event_mode):
        super().__init__()
        self.setMinimumSize(GAMEPLAY_WIDTH + GAMEPLAY_PADDING_WIDTH * 2,
            GAMEPLAY_HEIGHT + GAMEPLAY_PADDING_HEIGHT * 2)

        self.users = users
        # hash by username for convenience
        self.users_by_username = {user.username: user for user in self.users}
        self.events = events

        self.setMouseTracking(True)

        self.playback_start = 0
        self.clock = Timer(start_speed, self.playback_start)
        self.paused = False
        self.play_direction = 1

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.next_frame_from_timer)
        # 62 fps (1000ms / 60frames but the result can only be a integer)
        self.timer.start(int(1000/60))

        # let renderer normalize the events for us
        self.renderer = FrameRenderer(self, snitches, events, users,
            show_all_snitches, event_mode)

        self.playback_end = max(event.t for event in self.renderer.events)

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
        # to world (in-game) coordinates.

        x = self.renderer.world_x(x)
        y = self.renderer.world_y(y)
        self.renderer.current_mouse_x = x
        self.renderer.current_mouse_y = y

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
        self.renderer.paint_object = self
        self.renderer.t = int(self.clock.get_time())
        self.renderer.render()
