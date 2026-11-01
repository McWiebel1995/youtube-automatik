"""Symbol der Cicco Zentrale: kleine Insel mit Gebäuden bei Abendhimmel (.ico)."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw


def icon(size=256):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    s = size / 256
    d.rounded_rectangle([8 * s, 8 * s, 248 * s, 248 * s], radius=56 * s, fill=(20, 26, 48, 255))
    d.ellipse([170 * s, 34 * s, 206 * s, 70 * s], fill=(255, 201, 107, 255))           # Mond
    d.polygon([(36 * s, 176 * s), (220 * s, 176 * s), (196 * s, 214 * s), (60 * s, 214 * s)], fill=(61, 90, 58, 255))
    for x, w, h, c in ((58, 44, 70, (122, 111, 208)), (108, 40, 96, (90, 78, 168)), (154, 44, 56, (85, 104, 63))):
        d.rectangle([x * s, (176 - h) * s, (x + w) * s, 176 * s], fill=c + (255,))
        for yy in range(176 - h + 10, 170, 16):
            for xx in range(x + 8, x + w - 6, 13):
                d.rectangle([xx * s, yy * s, (xx + 6) * s, (yy + 7) * s], fill=(255, 210, 120, 255))
    return im


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "zentrale.ico")
    icon().save(out, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(out)
