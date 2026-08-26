import threading
import time
from PIL import Image

from daangn.errors import DaangnCancelledError


def image_contain_resize(img: Image.Image, size: tuple[int, int]):
    target_w, target_h = size

    img_copy = img.copy()
    img_copy.thumbnail((target_w, target_h))

    canvas = Image.new("RGB", (target_w, target_h), (255, 255, 255))

    x = (target_w - img_copy.width) // 2
    y = (target_h - img_copy.height) // 2
    canvas.paste(img_copy, (x, y))

    return canvas


class ReqLimitter:
    def __init__(self, min_delay_ms: int):
        self.min_delay_ms = min_delay_ms
        self.last_req = 0.0
        self.lock = threading.Lock()

    def wait(self, ev: threading.Event):
        with self.lock:
            elapsed_ms = (time.time() - self.last_req) * 1000
            wait_ms = self.min_delay_ms - elapsed_ms

            if wait_ms > 0:
                if ev.wait(wait_ms / 1000.0):
                    raise DaangnCancelledError()

            self.last_req = time.time()
