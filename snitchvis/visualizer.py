import numpy as np
from PyQt6.QtGui import QPalette, QColor, QShortcut
from PyQt6.QtWidgets import QMainWindow, QApplication
from PyQt6.QtCore import Qt

from snitchvis.interface import Interface

PREVIOUS_ERRSTATE = np.seterr('raise')

class Snitchvis(QMainWindow):
    def __init__(self, snitches, events,
        speeds=[0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 3.0, 5.0, 10.0],
        start_speed=1,
        show_all_snitches=False
    ):
        super().__init__()

        self.setAutoFillBackground(True)
        self.setWindowTitle("Visualizer")
        self.interface = Interface(snitches, events, speeds, start_speed,
            show_all_snitches)
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
    ``speeds`` must contain ``start_speed``, ``1``, ``0.75``, and ``1.5``.
    """
    def __init__(self, snitches, events,
        speeds=[0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 3.0, 5.0, 10.0],
        start_speed=1,
        show_all_snitches=False
    ):
        super().__init__([])
        self.setStyle("Fusion")
        self.setApplicationName("Circlevis")

        self.visualizer = None
        self.snitches = snitches
        self.events = events
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
        self.visualizer = Snitchvis(self.snitches, self.events, self.speeds,
            self.start_speed, self.show_all_snitches)
        self.visualizer.interface.renderer.loaded_signal.connect(self.on_load)
        self.visualizer.show()
        super().exec()

    def set_palette(self):
        accent = QColor(71, 174, 247)
        dark_p = QPalette()

        dark_p.setColor(QPalette.ColorGroup.Normal,   QPalette.ColorRole.Window, QColor(53, 53, 53))
        dark_p.setColor(QPalette.ColorGroup.Normal,   QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
        dark_p.setColor(QPalette.ColorGroup.Normal,   QPalette.ColorRole.Base, QColor(25, 25, 25))
        dark_p.setColor(QPalette.ColorGroup.Normal,   QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
        dark_p.setColor(QPalette.ColorGroup.Normal,   QPalette.ColorRole.ToolTipBase, QColor(53, 53, 53))
        dark_p.setColor(QPalette.ColorGroup.Normal,   QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
        dark_p.setColor(QPalette.ColorGroup.Normal,   QPalette.ColorRole.Text, Qt.GlobalColor.white)
        dark_p.setColor(QPalette.ColorGroup.Normal,   QPalette.ColorRole.Button, QColor(53, 53, 53))
        dark_p.setColor(QPalette.ColorGroup.Normal,   QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
        dark_p.setColor(QPalette.ColorGroup.Normal,   QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
        dark_p.setColor(QPalette.ColorGroup.Normal,   QPalette.ColorRole.Highlight, accent)
        dark_p.setColor(QPalette.ColorGroup.Inactive, QPalette.ColorRole.Highlight, Qt.GlobalColor.lightGray)
        dark_p.setColor(QPalette.ColorGroup.Normal,   QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
        dark_p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, Qt.GlobalColor.darkGray)
        dark_p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, Qt.GlobalColor.darkGray)
        dark_p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, Qt.GlobalColor.darkGray)
        dark_p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, QColor(53, 53, 53))
        dark_p.setColor(QPalette.ColorGroup.Normal,   QPalette.ColorRole.Link, accent)
        dark_p.setColor(QPalette.ColorGroup.Normal,   QPalette.ColorRole.LinkVisited, accent)

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
