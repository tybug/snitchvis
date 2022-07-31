from datetime import timedelta
import os
from enum import Enum, auto
from collections import defaultdict

from PyQt6.QtGui import QColor, QPainter, QPixmap, QPen
from PyQt6.QtCore import Qt, QPointF, QRectF, QRect

from snitchvis.utils import resource_path

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

# min width and height of our events bounding box. GAMEPLAY_PADDING_* gets
# applied on top of this.
BOUNDING_BOX_MIN_SIZE = 500

class Draw(Enum):
    ALL = auto()
    ONLY_BASE_FRAME = auto()
    ALL_EXCEPT_BASE_FRAME = auto()

# for use with line_profiler/kernprof, so I don't have to keep commenting out
# @profile lines or keep a line-profiler stash/branch
# https://github.com/pyutils/line_profiler
if "profile" not in __builtins__:
    def profile(f):
        return f

def draw(draw_mode):
    def decorator(f):
        def wrapper(self, *args, **kwargs):
            nonlocal draw_mode
            # if we're not using a base frame at all, then just draw everything
            # every frame (this is what the non-recording visualizer does)
            if self.base_frame is None and not self.drawing_base_frame:
                draw_mode = Draw.ALL

            if draw_mode == Draw.ONLY_BASE_FRAME and not self.drawing_base_frame:
                return
            if draw_mode == Draw.ALL_EXCEPT_BASE_FRAME and self.drawing_base_frame:
                return
            f(self, *args, **kwargs)

        return wrapper
    return decorator

class FrameRenderer:
    """
    Core of the drawing / painting occurs here. Responsible for drawing a single
    frame at a particular time to a generic paint object.

    Higher level code will handle changing the time and redrawing frames using
    this class as necessary.

    Originally split to allow drawing to either an image or a desktop renderer
    object.
    """
    @profile
    def __init__(self, paint_object, snitches, events, users, show_all_snitches,
        event_mode="square"):
        super().__init__()

        # filter out snitches which are broken or gone. We may want to display
        # these in a different color/shape later, or have a flag to display
        # missing snitches in a fancy way.
        snitches = [s for s in snitches if not s.broken_ts and not s.gone_ts]

        self.event_start_td = min(event.t for event in events)

        self.snitches_by_loc = {(s.x, s.y, s.z): s for s in snitches}

        for event in events:
            # normalize all event times to the earliest event, and convert to ms
            event.t = int((event.t - self.event_start_td).total_seconds() * 1000)

        events = sorted(events, key = lambda event: event.t)

        max_t = max(e.t for e in events)
        self.event_end_td = self.event_start_td + timedelta(milliseconds=max_t)
        self.users = users
        # hash by username for convenience
        self.users_by_username = {user.username: user for user in self.users}

        self.snitches = snitches
        self.events = events
        self.current_mouse_x = 0
        self.current_mouse_y = 0
        # 5 minutes, in ms (relative to game time)
        self.event_fade = 5 * 60 * 1000
        self.draw_coordinates = True
        # how to visualize events. One of "square" or "line". square highlights
        # the snitch the event was located at, and line draws lines between
        # events by the same player which aren't too far apart in time.
        self.event_mode = event_mode

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

        # should be the same as max_y - min_y after our adjustments above
        bounding_size = self.max_x - self.min_x
        if bounding_size < BOUNDING_BOX_MIN_SIZE:
            diff = BOUNDING_BOX_MIN_SIZE - bounding_size
            # expand both x and y by `bounding_size` to a total size of
            # BOUNDING_BOX_MIN_SIZE
            self.max_x += (diff / 2)
            self.min_x -= (diff / 2)
            self.max_y += (diff / 2)
            self.min_y -= (diff / 2)

        self.playback_start = 0
        self.playback_end = max(event.t for event in events)
        self.paused = False
        self.play_direction = 1

        self.paint_object = paint_object
        self.painter = None
        # a base frame to draw on top of. Allows us to "bake" expensive drawing
        # operations into a single base frame and draw that frame (which is a
        # pixmap) every time instead of lots of individual draw operations.
        # Anything drawn to this frame should remain static over the entire
        # duration of the visualization.
        self.base_frame = None
        self.drawing_base_frame = None
        self.visible_snitches = None

        # coordinate system calculations. see `update_coordinate_systems` for
        # documentation
        self.paint_width = None
        self.paint_height = None
        self.draw_width = None
        self.draw_height = None
        self.draw_size = None
        self.extra_padding_x = None
        self.extra_padding_y = None

        self.previous_paint_device_width = None
        self.previous_paint_device_height = None


        world_path = resource_path("world.png")
        os.environ['QT_IMAGEIO_MAXALLOC'] = "1000"
        self.world_pixmap = QPixmap(world_path)

        self.t = 0

    def update_coordinate_systems(self):
        # calculating coordinate based geometry can actually get very expensive
        # if we do it on every `scaled_{x,y}` call, since those functions can
        # get called hundreds or thousands of times per frame. We only need to
        # perform a recalculation when the screen size changes, or at every
        # frame at absolute worst.

        self.paint_width = self.paint_object.width()
        self.paint_height = self.paint_object.height()

        # Figure out the width of the draw area so we can scale our snitch
        # coordinates accordingly.
        self.draw_width = self.paint_width - 2 * GAMEPLAY_PADDING_WIDTH
        self.draw_height = self.paint_height - 2 * GAMEPLAY_PADDING_HEIGHT
        # draw area is always a square, so just pick the least of the two
        self.draw_size = min(self.draw_width, self.draw_height)

        # we actually need to do a bit more than this...if the renderer is wider
        # than it is tall, we'll have extra padding that we didn't account for.
        # figure out how much wider than tall we are (if at all) and pad by half
        # that amount to center us.
        self.extra_padding_x = max(self.paint_width - self.paint_height, 0) / 2
        self.extra_padding_y = max(self.paint_height - self.paint_width, 0) / 2

    def world_x(self, x):
        """
        Converts a screen x coordinate (`x`) to a world (in-game) coordinate.
        """
        x -= GAMEPLAY_PADDING_WIDTH + self.extra_padding_x
        # how far in to the snitch bounding box are we?
        ratio_x = x / self.draw_size
        return self.min_x + ratio_x * (self.max_x - self.min_x)

    def world_y(self, y):
        """
        Converts a screen y coordinate (`y`) to a world (in-game) coordinate.
        """
        y -= GAMEPLAY_PADDING_HEIGHT + self.extra_padding_y
        # how far in to the snitch bounding box are we?
        ratio_y = y / self.draw_size
        return self.min_y + ratio_y * (self.max_y - self.min_y)

    @profile
    def update_visible_snitches(self):
        # TODO add some tolerance for snitches on the GAMEPLAY_PADDING area,
        # or base the bounds off the actual screen width/height rather than
        # {min,max}{x,y}.
        # TODO vectorize this with numpy
        self.visible_snitches = []

        # avoid dot access for speed. probably a premature optimization, but
        # doesn't hurt.
        append = self.visible_snitches.append
        min_x = self.min_x
        max_x = self.max_x
        min_y = self.min_y
        max_y = self.max_y

        for snitch in self.snitches:
            # XXX don't split this out to two conditions, we want the short
            # circuiting
            if (min_x <= snitch.x <= max_x) and (min_y <= snitch.y <= max_y):
                append(snitch)

    @profile
    def screen_x(self, x):
        """
        Converts a world x coordinate (`x`) to a screen x coordinate (where 0
        is the top left corner in screen coordinate space).
        """
        # TODO even after precomputing as much as possible, `screen_x` and
        # `screen_y` *still* take long enough to make a dent in profiling
        # (`screen_point` makes up ~60% the call time of `draw_rectangle`).
        # We should probably vectorize this computation by computing coordinate
        # transforms for all snitches at once instead of one at a time.
        # We can also get some smaller (but still appreciable) gains by removing
        # the `self` calls - attribute acccess adds up!

        # * world coordinates: relative to the civmc map. eg -6750, 2300
        # * snitch bounding box coordinates: relative to the bounding box of the
        #   snitches we've been passed, which is the smallest square which
        #   contains all the passed snitches.
        # * view coordinates: relative to the full renderer widget, so 0,0 is
        #   just below the x button of the window
        # * draw coordinates: relative to the draw area of the renderer
        #   widget, which is the sub area of the view area after padding by
        #   GAMEPLAY_PADDING_HEIGHT and GAMEPLAY_PADDING_WIDTH. Will always be
        #   a square.

        # right now we have the world coordinates. We want view coordinates.
        # First, we'll convert to draw coordinates, then pad to get view
        # coordinates.

        # how far in to the snitch bounding box are we?
        snitch_bounding_box_ratio = (x - self.min_x) / (self.max_x - self.min_x)
        # multiply that by the width of the draw area to get our draw area
        # coordinates
        draw_area_coords = self.draw_size * snitch_bounding_box_ratio
        # pad by GAMEPLAY_PADDING_WIDTH to get the view coordinates
        draw_area_coords += GAMEPLAY_PADDING_WIDTH
        # see note on `self.extra_padding`
        draw_area_coords += self.extra_padding_x
        return draw_area_coords

    @profile
    def screen_y(self, y):
        """
        Converts a world y coordinate (`y`) to a screen y coordinate (where 0
        is the top left corner in screen coordinate space).
        """
        snitch_bounding_box_ratio = (y - self.min_y) / (self.max_y - self.min_y)
        draw_area_coords = self.draw_size * snitch_bounding_box_ratio
        draw_area_coords += GAMEPLAY_PADDING_HEIGHT
        draw_area_coords += self.extra_padding_y
        return draw_area_coords

    @profile
    def screen_point(self, x, y):
        x = self.screen_x(x)
        y = self.screen_y(y)
        return QPointF(x, y)

    @profile
    def render(self, drawing_base_frame=False):
        self.drawing_base_frame = drawing_base_frame
        self.painter = QPainter(self.paint_object)
        self.painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        # we only need to update some things (coordinate systems, snitch
        # visibility) whenever the size of the paint device changes.
        prev_pd_w = self.previous_paint_device_width
        prev_pd_h = self.previous_paint_device_height
        current_pd_w = self.paint_object.width()
        current_pd_h = self.paint_object.height()
        if prev_pd_w != current_pd_w or prev_pd_h != current_pd_h:
            self.update_coordinate_systems()
            self.update_visible_snitches()

        if self.base_frame:
            self.painter.drawImage(0, 0, self.base_frame)

        # world map
        self.draw_world_map()
        # time elapsed
        self.draw_info()
        # snitches
        self.draw_snitch_fields()
        self.draw_snitch_events()
        self.draw_snitch_blocks()

        self.painter.end()

        self.previous_paint_device_width = current_pd_w
        self.previous_paint_device_height = current_pd_h

    @profile
    @draw(Draw.ONLY_BASE_FRAME)
    def draw_world_map(self):
        world_min_x = self.world_x(0)
        world_min_y = self.world_y(0)
        world_max_x = self.world_x(self.paint_width)
        world_max_y = self.world_y(self.paint_height)

        # 0,0 is actually 10000,10000 in picture coordinates, so offset to
        # adjust.
        # world pixmap is also 2:1, so divide all coords by 2 to match.
        # TODO round up or down? might be an off by one error here
        world_min_x = int((world_min_x + 10000) / 2)
        world_min_y = int((world_min_y + 10000) / 2)
        world_max_x = int((world_max_x + 10000) / 2)
        world_max_y = int((world_max_y + 10000) / 2)

        # TODO what happens when world coords are negative? `copy` will silently
        # truncate/cap to 0, and we'll get a stretched image... ideally we'd
        # pad with black, but calculationss might be complicated.

        # # crop to the area we care about
        world_pixmap = self.world_pixmap.copy(world_min_x, world_min_y,
            world_max_x - world_min_x, world_max_y - world_min_y)

        opacity = self.painter.opacity()
        self.painter.setOpacity(0.13)
        self.painter.drawPixmap(0, 0, self.paint_width, self.paint_height,
            world_pixmap)
        self.painter.setOpacity(opacity)

    @profile
    @draw(Draw.ALL_EXCEPT_BASE_FRAME)
    def draw_info(self):
        # our current y coordinate for drawing info. Modified throughout this
        # function
        y = 15
        # x offset from edge of screen
        x_offset = 5

        start = self.event_start_td.strftime('%m/%d/%Y %H:%M')
        # if the snitch log only covers a single day, don't show mm/dd/yyyy
        # twice
        if self.event_start_td.date() == self.event_end_td.date():
            end = self.event_end_td.strftime('%H:%M')
        # different days, show full date for each
        else:
            end = self.event_end_td.strftime('%m/%d/%Y %H:%M')
        self.draw_text(x_offset, y, f"Snitch Log {start} - {end}")

        # draw current time
        y += 18
        timedelta_in = timedelta(milliseconds=self.t)
        current_t = self.event_start_td + timedelta_in
        self.draw_text(x_offset, y, current_t.strftime('%m/%d/%Y %H:%M:%S'))

        # draw all usernames with corresponding colors
        for user in self.users:
            y += 16

            alpha = 1 if user.enabled else 0.4
            start_x = 5
            start_y = y - 9
            self.draw_rectangle(start_x, start_y, start_x + 10, start_y + 10,
                color=user.color, alpha=alpha, coords="screen")

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

        if self.draw_coordinates:
            # draw current mouse coordinates
            y += 16
            self.draw_text(x_offset, y,
                f"{int(self.current_mouse_x)}, {int(self.current_mouse_y)}")

    @profile
    @draw(Draw.ONLY_BASE_FRAME)
    def draw_snitch_fields(self):
        for snitch in self.visible_snitches:
            self.draw_rectangle(snitch.x - 11, snitch.y - 11, snitch.x + 12,
                snitch.y + 12, color=SNITCH_FIELD_COLOR, alpha=0.23)

    @profile
    @draw(Draw.ALL_EXCEPT_BASE_FRAME)
    def draw_snitch_events(self):
        user_to_events = defaultdict(list)

        # snitch events
        for event in self.events:
            if not self.t - self.event_fade <= event.t <= self.t:
                continue

            snitch = self.snitches_by_loc[(event.x, event.y, event.z)]
            user = self.users_by_username[event.username]

            if self.event_mode == "line":
                # avoid drawing rectangles, we'll just draw lines
                user_to_events[user].append(event)
                continue

            # don't draw events from disabled users
            if not user.enabled:
                continue

            alpha = (1 - (self.t - event.t) / self.event_fade)
            self.draw_rectangle(snitch.x - 11, snitch.y - 11, snitch.x + 12,
                snitch.y + 12, color=user.color, alpha=alpha)

        for user, events in user_to_events.items():
            for event1, event2 in zip(events, events[1:]):
                # TODO use event1 or event2 to determine the fade here?
                alpha = (1 - (self.t - event1.t) / self.event_fade)
                self.draw_line(event1.x, event1.y, event2.x, event2.y,
                    color=user.color, alpha=alpha)


    @profile
    @draw(Draw.ONLY_BASE_FRAME)
    def draw_snitch_blocks(self):
        # actual snitch blocks. only draw if our snitch bounding box is
        # sufficiently large, otherwise these will just appear as single white
        # pixels and won't look good
        if self.max_x - self.min_x < 500:
            for snitch in self.visible_snitches:
                self.draw_rectangle(snitch.x, snitch.y, snitch.x + 1,
                    snitch.y + 1, color=SNITCH_BLOCK_COLOR)

    @profile
    def draw_rectangle(self, start_x, start_y, end_x, end_y, *, color, alpha=1,
        coords="world"
    ):
        color = QColor(color.red(), color.green(), color.blue())
        self.painter.setPen(Qt.PenStyle.NoPen)
        self.painter.setOpacity(alpha)
        self.painter.setBrush(color)

        # `coords` is either "screen" or "world". If screen, passed coords are
        # screen coords and don't need to be converted. Otherwise, passed coords
        # are world coords and need to first be converted to screen coords.
        if coords == "world":
            start = self.screen_point(start_x, start_y)
            end = self.screen_point(end_x, end_y)
        else:
            start = QPointF(start_x, start_y)
            end = QPointF(end_x, end_y)
        rect = QRectF(start, end)
        self.painter.drawRect(rect)

    @profile
    def draw_line(self, start_x, start_y, end_x, end_y, *, color, alpha=1):
        self.painter.setPen(QPen(color, 2))
        self.painter.setOpacity(alpha)
        self.painter.drawLine(self.screen_point(start_x, start_y),
            self.screen_point(end_x, end_y))

    @profile
    def draw_text(self, x, y, text, alpha=1):
        pen = self.painter.pen()
        self.painter.setPen(TEXT_COLOR)
        self.painter.setOpacity(alpha)
        self.painter.drawText(x, y, text)
        self.painter.setPen(pen)
