from PyQt6.QtWidgets import QGridLayout, QWidget, QSplitter, QFrame
from PyQt6.QtCore import Qt

from snitchvis.renderer import Renderer
from snitchvis.controls import VisualizerControls

class Interface(QWidget):
    def __init__(self, snitches, events, users, speeds, start_speed,
        show_all_snitches, event_mode):
        super().__init__()
        self.speeds = speeds

        self.renderer = Renderer(snitches, events, users, start_speed,
            show_all_snitches, event_mode)
        self.renderer.update_time_signal.connect(self.update_slider)
        # if the renderer wants to pause itself (eg when the playback hits the
        # end of the replay), we kick it back to us (the `Interface`) so we can
        # also update the pause button's state.
        self.renderer.pause_signal.connect(self.toggle_pause)
        self.controls = VisualizerControls(start_speed, events, users)
        self.controls.pause_button.clicked.connect(self.toggle_pause)
        self.controls.play_reverse_button.clicked.connect(self.play_reverse)
        self.controls.play_normal_button.clicked.connect(self.play_normal)
        self.controls.next_frame_button.clicked.connect(lambda: self.change_frame(reverse=False))
        self.controls.previous_frame_button.clicked.connect(lambda: self.change_frame(reverse=True))
        self.controls.speed_up_button.clicked.connect(self.increase_speed)
        self.controls.speed_down_button.clicked.connect(self.lower_speed)
        self.controls.time_slider.sliderMoved.connect(self.renderer.seek_to)
        self.controls.time_slider.setRange(self.renderer.playback_start, self.renderer.playback_end)

        self.controls.event_fade_changed.connect(self.event_fade_changed)

        self.splitter = QSplitter()
        # splitter lays widgets horizontally by default, so combine renderer and
        # controls into one single widget vertically
        self.splitter.addWidget(Combined([self.renderer, self.controls], Qt.Orientation.Vertical))

        layout = QGridLayout()
        layout.addWidget(self.splitter, 1, 0, 1, 1)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

    def play_normal(self):
        print("play normal")
        self.unpause()
        self.renderer.play_direction = 1
        self.update_speed(abs(self.renderer.clock.current_speed))

    def update_slider(self, value):
        self.controls.time_slider.setValue(value)

    def change_by(self, delta):
        self.pause()
        self.renderer.seek_to(self.renderer.clock.time_counter + delta)

    def play_reverse(self):
        self.unpause()
        self.renderer.play_direction = -1
        self.update_speed(abs(self.renderer.clock.current_speed))

    def update_speed(self, speed):
        self.renderer.clock.change_speed(speed * self.renderer.play_direction)

    def change_frame(self, reverse):
        self.pause()
        self.renderer.next_event(reverse=reverse)

    def toggle_pause(self):
        if self.renderer.paused:
            self.unpause()
        else:
            self.pause()

    def pause(self):
        self.controls.set_paused_state(True)
        self.renderer.pause()

    def unpause(self):
        self.controls.set_paused_state(False)
        self.renderer.resume()

    def lower_speed(self):
        index = self.speeds.index(abs(self.renderer.clock.current_speed))
        if index == 0:
            return
        speed = self.speeds[index - 1]
        self.controls.speed_label.setText(str(speed) + "x")
        self.update_speed(speed)

    def increase_speed(self):
        index = self.speeds.index(abs(self.renderer.clock.current_speed))
        if index == len(self.speeds) - 1:
            return
        speed = self.speeds[index + 1]
        self.controls.speed_label.setText(str(speed) + "x")
        self.update_speed(speed)

    def seek_to(self, time):
        self.pause()
        self.renderer.seek_to(time)

    def event_fade_changed(self, new_val):
        # convert minutes to ms
        self.renderer.event_fade = new_val * 60 * 1000
        self.renderer.update()

class Combined(QFrame):
    def __init__(self, widgets, direction):
        """
        combines all the widgets in `widgets` according to `direction`, which is
        one of `Qt.Horizontal` or `Qt.Vertical`
        """
        super().__init__()
        layout = QGridLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        if direction not in [Qt.Orientation.Horizontal, Qt.Orientation.Vertical]:
            raise ValueError("`direction` must be one of [Qt.Horizontal, "
                "Qt.Vertical]")

        for i, widget in enumerate(widgets):
            if direction == Qt.Orientation.Horizontal:
                layout.addWidget(widget, 0, i, 1, 1)
            else:
                layout.addWidget(widget, i, 0, 1, 1)

        self.setLayout(layout)
