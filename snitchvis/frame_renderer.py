from datetime import timedelta

from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtCore import Qt, QPointF, QRectF, QRect, QObject

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

# TODO does this even need to be a qobject?
class FrameRenderer(QObject):
    """
    Core of the drawing / painting occurs here. Responsible for drawing a single
    frame at a particular time to a generic paint object.

    Higher level code will handle changing the time and redrawing frames using
    this class as necessary.

    Originally split to allow drawing to either an image or a desktop renderer
    object.
    """
    def __init__(self, paint_object, snitches, events, users, show_all_snitches,
        event_start_td
    ):
        super().__init__()

        self.event_start_td = event_start_td
        max_t = max(e.t for e in events)
        self.event_end_td = event_start_td + timedelta(milliseconds=max_t)
        self.users = users
        # hash by username for convenience
        self.users_by_username = {user.username: user for user in self.users}

        self.snitches = snitches
        self.events = events
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

        self.paint_object = paint_object

        self.playback_start = 0
        self.playback_end = max(event.t for event in events)

        self.painter = None
        self.paused = False
        self.play_direction = 1

        # coordinate system calculations. see `update_coordinate_systems` for
        # documentation
        self.paint_width = None
        self.paint_height = None
        self.draw_width = None
        self.draw_height = None
        self.draw_size = None
        self.extra_padding_x = None
        self.extra_padding_y = None

        self.t = 0

    def update_coordinate_systems(self):
        # calculating coordinate based geometry can actually get very expensive
        # if we do it on every `scaled_{x,y}` call, since those functions can
        # get called hundreds or thousands of times per frame. We only need to
        # perform a recalculation when the screen size changes, or at every
        # frame at absolute worst.

        paint_device = self.painter.device()
        self.paint_width = paint_device.width()
        self.paint_height = paint_device.height()

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

    def scaled_y(self, y):
        snitch_bounding_box_ratio = (y - self.min_y) / (self.max_y - self.min_y)
        draw_area_coords = self.draw_size * snitch_bounding_box_ratio
        draw_area_coords += GAMEPLAY_PADDING_HEIGHT
        draw_area_coords += self.extra_padding_y
        return draw_area_coords


    def scaled_point(self, x, y):
        return QPointF(self.scaled_x(x), self.scaled_y(y))

    def render(self):
        self.painter = QPainter(self.paint_object)
        self.painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        self.update_coordinate_systems()

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
        # snitch fields
        for snitch in self.snitches:
            # only draw visible snitches
            # TODO add some tolerance for snitches on the GAMEPLAY_PADDING area,
            # or base the bounds off the actual screen width/height rather than
            # {min,max}{x,y}.
            if (self.min_x <= snitch.x <= self.max_x) and (self.min_y <= snitch.y <= self.max_y):
                self.draw_rectangle(snitch.x - 11, snitch.y - 11,
                    snitch.x + 12, snitch.y + 12, color=SNITCH_FIELD_COLOR,
                    alpha=0.23)

        # snitch events
        for snitch in self.snitches:
            color = None
            alpha = None

            for event in snitch.events:
                if not self.t - self.snitch_event_limit <= event.t <= self.t:
                    continue
                user = self.users_by_username[event.username]
                # don't draw events from disabled users
                if not user.enabled:
                    continue
                color = user.color
                alpha = (1 - (self.t - event.t) / self.snitch_event_limit)

            if not (color and alpha):
                continue
            self.draw_rectangle(snitch.x - 11, snitch.y - 11, snitch.x + 12,
                snitch.y + 12, color=color, alpha=alpha)

        # actual snitch blocks. only draw if our snitch bounding box is
        # sufficiently large, otherwise these will just appear as single white
        # pixels and won't look good
        if self.max_x - self.min_x < 500:
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
