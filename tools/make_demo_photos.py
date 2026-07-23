"""Generate the bundled demo photo pack (committed to static/demo/).

Reproducible, no network, no real-world imagery: these are drawn scenes of a
fictional street, carrying synthetic EXIF GPS anchored to Cedar Canyon so the
photo pipeline resolves them exactly as a real geotagged phone photo would.

    python -m tools.make_demo_photos
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFilter
from PIL.TiffImagePlugin import IFDRational

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.seeds import street_latlng  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "static", "demo")
W, H = 480, 320


def _dms(v):
    v = abs(v)
    d = int(v)
    m = int((v - d) * 60)
    s = (((v - d) * 60) - m) * 60
    return (IFDRational(d, 1), IFDRational(m, 1), IFDRational(round(s * 100), 100))


def _scene(glow: float, smoke: float) -> Image.Image:
    """glow/smoke in 0..1 — a hillside at dusk with fire beyond the ridge."""
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)

    # Sky: night blue at the top, washing to ember as the fire front nears.
    # At high glow this is a photo taken close to an active front, so most of
    # the frame legitimately sits in the fire-glow band.
    for y in range(H):
        t = y / H
        warm = glow * min(1.0, (t + 0.15) ** 1.1)
        r = int(26 + 225 * warm)
        g = int(28 + 95 * warm * 0.75)
        b = int(44 * (1 - warm) + 26 * warm)
        d.line([(0, y), (W, y)], fill=(min(255, r), min(255, g), max(0, b)))

    # Fire front beyond the ridge — a broad band, not a thin line.
    if glow > 0.05:
        fy = int(H * 0.60)
        band = int(H * 0.30 * glow)
        for i in range(160):
            x = int((i * 61) % W)
            h = int(band * (0.45 + ((i % 13) / 13) * 0.75))
            d.rectangle([x, fy - h, x + 9, fy + 6],
                        fill=(255, int(150 - 70 * glow), 34))
        img = img.filter(ImageFilter.GaussianBlur(radius=4 + 5 * glow))
        d = ImageDraw.Draw(img)

    # Ridgeline + dark foreground, kept low so the fire stays the subject.
    d.polygon([(0, H * 0.80), (W * 0.3, H * 0.74), (W * 0.55, H * 0.82),
               (W * 0.8, H * 0.75), (W, H * 0.83), (W, H), (0, H)],
              fill=(20, 16, 13))
    # A couple of poles so it reads as a roadside, not an abstract gradient.
    for px in (int(W * 0.22), int(W * 0.68)):
        d.rectangle([px, int(H * 0.60), px + 3, int(H * 0.82)], fill=(14, 11, 10))

    # Smoke haze over everything.
    if smoke > 0.02:
        haze = Image.new("RGB", (W, H), (168, 165, 158))
        img = Image.blend(img, haze, min(0.75, smoke))
    return img


def write(name, street, when, glow, smoke):
    lat, lng = street_latlng(street)
    img = _scene(glow, smoke)
    exif = img.getexif()
    exif[0x8825] = {1: "N" if lat >= 0 else "S", 2: _dms(lat),
                    3: "E" if lng >= 0 else "W", 4: _dms(lng)}
    exif[0x0132] = when
    path = os.path.join(OUT, name)
    img.save(path, "JPEG", quality=88, exif=exif.tobytes())
    print(f"  {name:16} {street:16} {when}  {os.path.getsize(path):>6} bytes")


def main():
    os.makedirs(OUT, exist_ok=True)
    print(f"writing demo photos -> {OUT}")
    # One street, three moments: the fire arriving, then taking the road.
    write("mb-1.jpg", "miner's bend", "2026:07:23 19:50:00", glow=0.62, smoke=0.05)
    write("mb-2.jpg", "miner's bend", "2026:07:23 19:56:00", glow=0.95, smoke=0.10)
    write("mb-3.jpg", "miner's bend", "2026:07:23 20:02:00", glow=0.20, smoke=0.62)
    # A second street, so the map shows more than one hazard.
    write("gp-1.jpg", "granite pass", "2026:07:23 19:58:00", glow=0.80, smoke=0.12)


if __name__ == "__main__":
    main()
