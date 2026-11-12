"""Draw the solar-orb icon (prometheus.ico) with Pillow, so no binary image is kept in the repository."""

import math
import sys

from PIL import Image


def orb(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size))
    px = img.load()
    c = (size - 1) / 2
    stops = [(0.0, (255, 244, 194, 255)), (0.45, (255, 179, 0, 255)), (0.8, (230, 81, 0, 255)), (1.0, (230, 81, 0, 0))]
    for y in range(size):
        for x in range(size):
            t = min(1.0, math.hypot(x - c, y - c) / (size / 2))
            for (a, ca), (b, cb) in zip(stops, stops[1:]):
                if a <= t <= b:
                    f = (t - a) / (b - a)
                    px[x, y] = tuple(round(ca[i] + (cb[i] - ca[i]) * f) for i in range(4))
                    break
    return img


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "prometheus.ico"
    orb(256).save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(out)
