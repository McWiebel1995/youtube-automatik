"""Kleine Zeichen-Bibliothek: freundliche, flache Kinder-Grafiken mit PIL."""
import math
from pathlib import Path

from PIL import ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
_fonts = {}


def font(size, weight="SemiBold", family="Kids"):
    """family = Dateiname in assets/fonts (z. B. "Pacifico", "Quicksand"); Fallback: Kids/Fredoka, DejaVu."""
    key = (size, weight, family)
    if key not in _fonts:
        f = None
        for p in [ROOT / f"assets/fonts/{family}.ttf", ROOT / "assets/fonts/Kids.ttf",
                  Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")]:
            if p.exists():
                try:
                    f = ImageFont.truetype(str(p), size)
                    try:
                        f.set_variation_by_name(weight)
                    except Exception:  # noqa: BLE001 – keine variable Schrift
                        pass
                    break
                except OSError:
                    continue
        _fonts[key] = f or ImageFont.load_default(size)
    return _fonts[key]


def darker(c, k=0.75):
    return tuple(int(v * k) for v in c[:3])


def lighter(c, k=0.35):
    return tuple(int(v + (255 - v) * k) for v in c[:3])


# ----------------------------------------------------------------- Formen
def poly_regular(cx, cy, r, n, rot=-90):
    return [(cx + r * math.cos(math.radians(rot + 360 * i / n)),
             cy + r * math.sin(math.radians(rot + 360 * i / n))) for i in range(n)]


def star_points(cx, cy, r, n=5, inner=0.45):
    pts = []
    for i in range(n * 2):
        rr = r if i % 2 == 0 else r * inner
        a = math.radians(-90 + 180 * i / n)
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    return pts


def heart_points(cx, cy, r):
    pts = []
    for i in range(80):
        t = 2 * math.pi * i / 80
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((cx + x * r / 17, cy - y * r / 17))
    return pts


def shape(d: ImageDraw.ImageDraw, kind, cx, cy, r, color, outline=True):
    ow = max(3, int(r * 0.07)) if outline else 0
    oc = darker(color)
    if kind == "kreis":
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color, outline=oc, width=ow)
    elif kind == "oval":
        d.ellipse([cx - r * 0.72, cy - r, cx + r * 0.72, cy + r], fill=color, outline=oc, width=ow)
    elif kind == "quadrat":
        d.rounded_rectangle([cx - r * 0.85, cy - r * 0.85, cx + r * 0.85, cy + r * 0.85], r * 0.08,
                            fill=color, outline=oc, width=ow)
    elif kind == "rechteck":
        d.rounded_rectangle([cx - r * 1.2, cy - r * 0.65, cx + r * 1.2, cy + r * 0.65], r * 0.08,
                            fill=color, outline=oc, width=ow)
    elif kind == "dreieck":
        d.polygon(poly_regular(cx, cy + r * 0.15, r * 1.05, 3), fill=color, outline=oc, width=ow)
    elif kind == "raute":
        d.polygon([(cx, cy - r), (cx + r * 0.7, cy), (cx, cy + r), (cx - r * 0.7, cy)],
                  fill=color, outline=oc, width=ow)
    elif kind == "sechseck":
        d.polygon(poly_regular(cx, cy, r, 6, rot=0), fill=color, outline=oc, width=ow)
    elif kind == "stern":
        d.polygon(star_points(cx, cy, r), fill=color, outline=oc, width=ow)
    elif kind == "herz":
        d.polygon(heart_points(cx, cy + r * 0.05, r), fill=color, outline=oc, width=ow)


def face(d, cx, cy, r, blink=False):
    """Kleines freundliches Gesicht."""
    ex, ey, er = r * 0.32, r * 0.12, max(2, r * 0.09)
    for sx in (-1, 1):
        if blink:
            d.line([cx + sx * ex - er, cy - ey, cx + sx * ex + er, cy - ey], fill=(40, 30, 40), width=int(er * 0.8))
        else:
            d.ellipse([cx + sx * ex - er, cy - ey - er, cx + sx * ex + er, cy - ey + er], fill=(40, 30, 40))
    d.arc([cx - r * 0.3, cy - r * 0.1, cx + r * 0.3, cy + r * 0.35], 20, 160, fill=(40, 30, 40),
          width=max(2, int(r * 0.07)))
    d.ellipse([cx - r * 0.55, cy + r * 0.05, cx - r * 0.35, cy + r * 0.2], fill=(255, 150, 160))
    d.ellipse([cx + r * 0.35, cy + r * 0.05, cx + r * 0.55, cy + r * 0.2], fill=(255, 150, 160))


# ----------------------------------------------------------------- Dinge
def balloon(d, cx, cy, r, color):
    d.line([cx, cy + r * 1.15, cx + r * 0.15, cy + r * 1.6, cx - r * 0.1, cy + r * 2.1],
           fill=(120, 120, 120), width=max(2, int(r * 0.04)))
    d.polygon([(cx - r * 0.12, cy + r * 1.2), (cx + r * 0.12, cy + r * 1.2), (cx, cy + r * 1.05)],
              fill=darker(color))
    d.ellipse([cx - r * 0.85, cy - r, cx + r * 0.85, cy + r * 1.15], fill=color, outline=darker(color),
              width=max(2, int(r * 0.05)))
    d.ellipse([cx - r * 0.5, cy - r * 0.65, cx - r * 0.2, cy - r * 0.2], fill=lighter(color, 0.55))


def apple(d, cx, cy, r, color=(220, 40, 40)):
    d.ellipse([cx - r, cy - r * 0.85, cx + r, cy + r], fill=color, outline=darker(color), width=max(2, int(r * 0.05)))
    d.ellipse([cx - r * 0.18, cy - r * 0.95, cx + r * 0.18, cy - r * 0.68], fill=darker(color, 0.7))
    d.line([cx, cy - r * 0.75, cx + r * 0.1, cy - r * 1.15], fill=(110, 70, 40), width=max(3, int(r * 0.1)))
    d.ellipse([cx + r * 0.1, cy - r * 1.15, cx + r * 0.6, cy - r * 0.85], fill=(76, 175, 80))
    d.ellipse([cx - r * 0.6, cy - r * 0.45, cx - r * 0.3, cy - r * 0.1], fill=lighter(color, 0.5))


def fish(d, cx, cy, r, color):
    d.polygon([(cx + r * 0.6, cy), (cx + r * 1.2, cy - r * 0.55), (cx + r * 1.2, cy + r * 0.55)],
              fill=darker(color, 0.85))
    d.ellipse([cx - r, cy - r * 0.6, cx + r * 0.8, cy + r * 0.6], fill=color)
    d.ellipse([cx - r * 0.6, cy - r * 0.25, cx - r * 0.35, cy], fill=(255, 255, 255))
    d.ellipse([cx - r * 0.52, cy - r * 0.17, cx - r * 0.42, cy - r * 0.07], fill=(30, 30, 30))


def star_thing(d, cx, cy, r, color=(255, 205, 40)):
    d.polygon(star_points(cx, cy, r), fill=color, outline=darker(color), width=max(2, int(r * 0.06)))
    face(d, cx, cy + r * 0.08, r * 0.45)


THINGS = {
    "ballon": dict(one="Ballon", many="Ballons", draw=balloon),
    "apfel": dict(one="Apfel", many="Äpfel", draw=lambda d, x, y, r, c: apple(d, x, y, r)),
    "fisch": dict(one="Fisch", many="Fische", draw=fish),
    "stern": dict(one="Stern", many="Sterne", draw=lambda d, x, y, r, c: star_thing(d, x, y, r)),
}


# ----------------------------------------------------------------- Beispiele für Farben
def strawberry(d, cx, cy, r, c):
    d.polygon([(cx - r, cy - r * 0.4), (cx + r, cy - r * 0.4), (cx, cy + r * 1.1)], fill=c)
    d.ellipse([cx - r, cy - r * 0.9, cx + r, cy + r * 0.3], fill=c)
    for i in range(9):
        sx = cx + (i % 3 - 1) * r * 0.45 + (i // 3 % 2) * r * 0.15
        sy = cy - r * 0.25 + (i // 3) * r * 0.32
        d.ellipse([sx - 4, sy - 6, sx + 4, sy + 6], fill=(255, 235, 120))
    d.polygon(star_points(cx, cy - r * 0.8, r * 0.55, 5, 0.4), fill=(56, 142, 60))


def sun(d, cx, cy, r, c):
    for i in range(12):
        a = 2 * math.pi * i / 12
        d.line([cx + r * 1.15 * math.cos(a), cy + r * 1.15 * math.sin(a),
                cx + r * 1.55 * math.cos(a), cy + r * 1.55 * math.sin(a)], fill=c, width=int(r * 0.12))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c, outline=darker(c, 0.9), width=4)
    face(d, cx, cy, r * 0.8)


def sky(d, cx, cy, r, c):
    d.rounded_rectangle([cx - r * 1.4, cy - r, cx + r * 1.4, cy + r], r * 0.2, fill=c)
    for ox, oy, rr in [(-0.4, 0.1, 0.35), (0.0, -0.05, 0.45), (0.4, 0.1, 0.35)]:
        d.ellipse([cx + ox * r - rr * r, cy + oy * r - rr * r, cx + ox * r + rr * r, cy + oy * r + rr * r],
                  fill=(255, 255, 255))


def grass(d, cx, cy, r, c):
    for i in range(14):
        x = cx - r * 1.3 + i * r * 0.2
        d.polygon([(x - r * 0.1, cy + r), (x + r * 0.1, cy + r), (x + r * 0.05 * ((i % 3) - 1), cy - r * (0.5 + 0.4 * ((i * 7) % 3) / 2))],
                  fill=darker(c, 0.8 + 0.2 * (i % 2)))


def carrot(d, cx, cy, r, c):
    d.polygon([(cx - r * 0.45, cy - r * 0.6), (cx + r * 0.45, cy - r * 0.6), (cx, cy + r * 1.2)], fill=c)
    for k in (-1, 0, 1):
        d.ellipse([cx + k * r * 0.2 - r * 0.12, cy - r * 1.2, cx + k * r * 0.2 + r * 0.12, cy - r * 0.55],
                  fill=(67, 160, 71))
    for i in range(3):
        y = cy - r * 0.3 + i * r * 0.35
        d.line([cx - r * 0.25 + i * r * 0.07, y, cx - r * 0.05 + i * r * 0.05, y], fill=darker(c), width=4)


def plum(d, cx, cy, r, c):
    d.ellipse([cx - r * 0.85, cy - r, cx + r * 0.85, cy + r], fill=c)
    d.arc([cx - r * 0.3, cy - r, cx + r * 0.3, cy + r], 270, 90, fill=darker(c), width=5)
    d.ellipse([cx + r * 0.05, cy - r * 1.3, cx + r * 0.65, cy - r * 0.95], fill=(76, 175, 80))


def piglet(d, cx, cy, r, c):
    for sx in (-1, 1):
        d.polygon([(cx + sx * r * 0.45, cy - r * 0.7), (cx + sx * r * 0.95, cy - r * 1.05), (cx + sx * r * 0.85, cy - r * 0.35)],
                  fill=darker(c, 0.9))
    d.ellipse([cx - r, cy - r * 0.9, cx + r, cy + r * 0.9], fill=c)
    d.ellipse([cx - r * 0.38, cy + r * 0.05, cx + r * 0.38, cy + r * 0.5], fill=darker(c, 0.85))
    for sx in (-1, 1):
        d.ellipse([cx + sx * r * 0.15 - 7, cy + r * 0.2, cx + sx * r * 0.15 + 7, cy + r * 0.35], fill=darker(c, 0.6))
        d.ellipse([cx + sx * r * 0.38 - 9, cy - r * 0.35, cx + sx * r * 0.38 + 9, cy - r * 0.17], fill=(40, 30, 40))


def chocolate(d, cx, cy, r, c):
    d.rounded_rectangle([cx - r * 0.9, cy - r * 1.1, cx + r * 0.9, cy + r * 1.1], 14, fill=c)
    for i in range(1, 3):
        x = cx - r * 0.9 + i * r * 0.6
        d.line([x, cy - r * 1.1, x, cy + r * 1.1], fill=darker(c), width=5)
    for i in range(1, 4):
        y = cy - r * 1.1 + i * r * 0.55
        d.line([cx - r * 0.9, y, cx + r * 0.9, y], fill=darker(c), width=5)


def snowman(d, cx, cy, r, c):
    d.ellipse([cx - r * 0.75, cy - r * 0.1, cx + r * 0.75, cy + r * 1.3], fill=c, outline=(200, 210, 225), width=4)
    d.ellipse([cx - r * 0.5, cy - r * 0.95, cx + r * 0.5, cy + r * 0.05], fill=c, outline=(200, 210, 225), width=4)
    d.polygon([(cx, cy - r * 0.45), (cx + r * 0.35, cy - r * 0.38), (cx, cy - r * 0.32)], fill=(251, 140, 0))
    for sx in (-1, 1):
        d.ellipse([cx + sx * r * 0.18 - 6, cy - r * 0.68, cx + sx * r * 0.18 + 6, cy - r * 0.56], fill=(30, 30, 30))


def night(d, cx, cy, r, c):
    d.rounded_rectangle([cx - r * 1.4, cy - r, cx + r * 1.4, cy + r], r * 0.2, fill=c)
    d.ellipse([cx - r * 0.2, cy - r * 0.6, cx + r * 0.6, cy + r * 0.2], fill=(255, 240, 180))
    d.ellipse([cx + 0.05 * r, cy - r * 0.7, cx + r * 0.75, cy + r * 0.05], fill=c)
    for sx, sy in [(-1.0, -0.5), (-0.6, 0.4), (0.9, 0.5), (-0.2, -0.2), (1.0, -0.6)]:
        d.polygon(star_points(cx + sx * r, cy + sy * r, r * 0.12), fill=(255, 230, 120))


def elephant(d, cx, cy, r, c):
    d.ellipse([cx - r * 1.05, cy - r * 0.75, cx - r * 0.35, cy + r * 0.25], fill=darker(c, 0.9))
    d.ellipse([cx + r * 0.35, cy - r * 0.75, cx + r * 1.05, cy + r * 0.25], fill=darker(c, 0.9))
    d.ellipse([cx - r * 0.6, cy - r * 0.8, cx + r * 0.6, cy + r * 0.4], fill=c)
    d.rounded_rectangle([cx - r * 0.13, cy, cx + r * 0.13, cy + r * 0.95], r * 0.12, fill=c)
    for sx in (-1, 1):
        d.ellipse([cx + sx * r * 0.25 - 7, cy - r * 0.35, cx + sx * r * 0.25 + 7, cy - r * 0.2], fill=(40, 30, 40))


COLOR_EXAMPLES = {
    "rot": strawberry, "gelb": sun, "blau": sky, "grün": grass, "orange": carrot, "lila": plum,
    "rosa": piglet, "braun": chocolate, "weiß": snowman, "schwarz": night, "grau": elephant,
}


def ease_back(x):
    x = min(1.0, max(0.0, x))
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


def label(d, text, cx, cy, size, color=(60, 50, 90), box=(255, 255, 255)):
    f = font(size)
    w = d.textlength(text, font=f)
    pad_x, pad_y = size * 0.45, size * 0.25
    d.rounded_rectangle([cx - w / 2 - pad_x, cy - size / 2 - pad_y, cx + w / 2 + pad_x, cy + size / 2 + pad_y * 1.4],
                        size * 0.45, fill=box)
    d.text((cx, cy), text, font=f, fill=color, anchor="mm")
