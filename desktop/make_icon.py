"""Erzeugt das ClipWerk-Symbol (Filmstreifen + Schere in Lampengelb auf dunklem Holz) als .ico."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw


def icon(size=256):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    s = size / 256
    d.rounded_rectangle([8 * s, 8 * s, 248 * s, 248 * s], radius=56 * s, fill=(36, 32, 27, 255))
    # Filmstreifen
    d.rounded_rectangle([46 * s, 54 * s, 210 * s, 150 * s], radius=14 * s, fill=(242, 181, 68, 255))
    for k in range(5):
        x = 58 * s + k * 32 * s
        d.rectangle([x, 62 * s, x + 16 * s, 72 * s], fill=(36, 32, 27, 255))
        d.rectangle([x, 132 * s, x + 16 * s, 142 * s], fill=(36, 32, 27, 255))
    d.polygon([(112 * s, 86 * s), (112 * s, 118 * s), (140 * s, 102 * s)], fill=(36, 32, 27, 255))
    # Schere
    c = (139, 195, 74, 255)
    d.line([(88 * s, 214 * s), (168 * s, 150 * s)], fill=c, width=int(12 * s))
    d.line([(168 * s, 214 * s), (88 * s, 150 * s)], fill=c, width=int(12 * s))
    for cx in (80, 176):
        d.ellipse([(cx - 20) * s, 196 * s, (cx + 20) * s, 236 * s], outline=c, width=int(10 * s))
    return im


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "clipwerk.ico")
    out.parent.mkdir(parents=True, exist_ok=True)
    icon().save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    icon().save(out.with_suffix(".png"))
