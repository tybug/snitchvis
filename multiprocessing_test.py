from snitchvis.frame_renderer import FrameRenderer
from snitchvis.visualizer import Event

from datetime import datetime
from subprocess import Popen, PIPE
from multiprocessing import Pool

from PIL.ImageQt import fromqimage
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QTimer

class SnitchVisRecord(QApplication):
    def __init__(self, snitches, events, users, show_all_snitches,
        event_start_td):
        # https://stackoverflow.com/q/13215120
        super().__init__(['-platform', 'minimal'])

        self.snitches = snitches
        self.events = events
        self.users = users
        self.show_all_snitches = show_all_snitches
        self.event_start_td = event_start_td
        self.renderer = None

        # frames per second
        self.framerate = 30
        # seconds
        video_duration = 10

        max_t = max(e.t for e in self.events)
        actual_duration = max_t / 1000

        # our video is `actual_duration` seconds long, and we need to compress
        # that into `video_duration` seconds at `framerate` fps.
        # we have `framerate * video_duration` frames to work with, and each
        # frame needs to take `actual_duration / num_frames` seconds

        self.num_frames = int(video_duration * self.framerate)
        # in ms
        self.frame_duration = (actual_duration / self.num_frames) * 1000

        QTimer.singleShot(0, self.start)

    def start(self):
        pass

    def render_frame(self, frame_num):
        if self.renderer is None:
            self.renderer = FrameRenderer(None, self.snitches, self.events,
                self.users, self.show_all_snitches, self.event_start_td)

        print(f"rendering frame {frame_num} / {self.num_frames}")
        image = QImage(1000, 1000, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.black)

        self.renderer.paint_object = image
        self.renderer.t = int(frame_num * self.frame_duration)
        self.renderer.render()

        return fromqimage(image)

    def exec(self):
        images = []

        for i in range(self.num_frames):
            image = self.render_frame(i)
            images.append(image)

        generate_video(images, self.framerate)
        QApplication.quit()

def generate_video(images, framerate):
    # https://stackoverflow.com/a/13298538
    # -y overwrites output file if exists
    # -r specifies framerate (frames per second)
    p = Popen(["ffmpeg", "-y", "-f", "image2pipe", "-r", str(framerate),
        "-vcodec", "mjpeg", "-pix_fmt", "yuv420p", "-i", "-", "-vf",
        "scale=1000:1000", "out_ffmpeg.mp4"],
        stdin=PIPE)

    for i, im in enumerate(images):
        print(f"saving image {i} to stdin")
        im.save(p.stdin, "JPEG")
    p.stdin.close()

    print("converting images to video with ffmpeg")
    p.wait()


events = [Event("username", None, None, 100, 100, 100, 1000)]

vis = None
def set_vis():
    global vis
    vis = SnitchVisRecord([], events, [], False, datetime.now())

def render_frame(frame_num):
    return vis.render_frame(frame_num)


if __name__ == "__main__":
    import time
    t = time.time()
    pool = Pool(processes=8, initializer=set_vis)
    images = pool.map(render_frame, range(3000))
    print("EEEEEEEEEE 1", time.time() - t)
    generate_video(images, 30)
    print("EEEEEEEEEE 2", time.time() - t)

# there's basically no speedup, wtf? am I not doing multiprocessing right with
# qt?

# 8 cores, 300 images
# EEEEEEEEEE 1 3.326064109802246
# EEEEEEEEEE 2 5.913705110549927

# 4 cores, 3000 images
# EEEEEEEEEE 1 25.79093074798584
# EEEEEEEEEE 2 51.39500689506531

# 8 cores, 3000 images
# EEEEEEEEEE 1 31.29591679573059
