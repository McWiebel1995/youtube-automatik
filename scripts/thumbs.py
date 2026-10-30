#!/usr/bin/env python3
"""
Gestaltete YouTube-Thumbnails (1280x720) für die langen Videos – je Kanal ein eigener, wiedererkennbarer Stil:

  whatif(bg, "EARTH STOPS?", out)                 Beyond the If: Hero-Bild, 2–4 Wörter groß, letztes Wort gelb
  calm(bg, "regen", 3, "Fall Asleep Fast", out)  Calm Haven: Foto, ruhiger Serif-Hook, Stunden-Plakette
  kids(bg, "schlaf", "Sternenhimmel", "15 MIN", out)   Mondmelodie / Gute-Nacht-Kiste: Rund, bunt, freundlich

Gute Thumbnails: wenige große Wörter, starker Kontrast, ein klares Motiv, auf dem Handy in 2 cm Breite lesbar.
"""
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"
W, H = 1280, 720
FALLBACK = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def font(name, size, variation="Bold"):
    try:
        f = ImageFont.truetype(str(FONTS / name), size)
        if variation:
            try:
                f.set_variation_by_name(variation)
            except Exception:  # noqa: BLE001
                pass
        return f
    except Exception:  # noqa: BLE001
        return ImageFont.truetype(FALLBACK, size)


def cover(img_path, w=W, h=H, focus=0.5):
    im = Image.open(img_path).convert("RGB")
    s = max(w / im.width, h / im.height)
    im = im.resize((int(im.width * s + 1), int(im.height * s + 1)), Image.LANCZOS)
    x = int((im.width - w) * focus)
    y = (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def wrap(draw, text, fnt, max_w):
    words, lines, cur = text.split(), [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if cur and draw.textlength(t, font=fnt) > max_w:
            lines.append(cur)
            cur = wd
        else:
            cur = t
    if cur:
        lines.append(cur)
    return lines


def fit(draw, text, name, max_w, max_lines, start, smallest, variation="Bold"):
    size = start
    while True:
        f = font(name, size, variation)
        lines = wrap(draw, text, f, max_w)
        if (len(lines) <= max_lines and all(draw.textlength(ln, font=f) <= max_w for ln in lines)) or size <= smallest:
            return f, lines, size
        size -= 4


def shadow_layer(size, draw_fn, blur, opacity=200):
    lay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(lay), (0, 0, 0, opacity))
    return lay.filter(ImageFilter.GaussianBlur(blur))


def vignette(im, strength=0.55, side=None):
    """Abdunkeln an den Rändern (oder nur links/unten) – Text wird lesbar, Motiv bleibt hell."""
    mask = Image.new("L", im.size, 0)
    d = ImageDraw.Draw(mask)
    w, h = im.size
    if side == "left":
        for x in range(w):
            d.line([(x, 0), (x, h)], fill=int(255 * strength * max(0, 1 - x / (w * 0.62)) ** 1.3))
    elif side == "bottom":
        for y in range(h):
            d.line([(0, y), (w, y)], fill=int(255 * strength * max(0, (y - h * 0.38) / (h * 0.62)) ** 1.2))
    else:
        for i in range(60):
            a = int(255 * strength * (1 - i / 60) ** 2)
            d.rectangle([i * w // 200, i * h // 200, w - i * w // 200, h - i * h // 200], outline=a, width=max(1, w // 200))
        mask = mask.filter(ImageFilter.GaussianBlur(40))
    return Image.composite(Image.new("RGB", im.size, (0, 0, 0)), im, mask)


def pill(draw, xy, text, fnt, fill, color, pad=(22, 10), radius=None):
    x, y = xy
    tw = draw.textlength(text, font=fnt)
    asc, desc = fnt.getmetrics()
    box = [x, y, x + tw + 2 * pad[0], y + asc + desc + 2 * pad[1] - 6]
    draw.rounded_rectangle(box, radius=radius or (box[3] - box[1]) // 2, fill=fill)
    draw.text((x + pad[0], y + pad[1] - 4), text, font=fnt, fill=color)
    return box


# ----------------------------------------------------------------- Beyond the If
def whatif(bg, text, out, badge="WHAT IF?"):
    """Hero-Bild rechts, links 2–4 Wörter in fetter Schrift (weiß, letztes Wort gelb), dicke Kontur."""
    im = cover(bg, focus=0.65)
    im = ImageEnhance.Contrast(im).enhance(1.18)
    im = ImageEnhance.Color(im).enhance(1.25)
    im = vignette(im, 0.82, "left")
    d = ImageDraw.Draw(im)
    text = " ".join(text.upper().split()[:5])
    f, lines, size = fit(d, text, "Anton.ttf", 640, 3, 190, 90, variation=None)
    lh = int(size * 1.02)
    y0 = (H - lh * len(lines)) // 2 + 30
    words_last = lines[-1].split()

    def draw_text(dr, fill=None):
        y = y0
        for i, ln in enumerate(lines):
            if fill:
                dr.text((56, y), ln, font=f, fill=fill)
            else:
                if i == len(lines) - 1 and len(words_last) >= 1:
                    head = " ".join(words_last[:-1])
                    x = 56
                    if head:
                        dr.text((x, y), head + " ", font=f, fill=(255, 255, 255), stroke_width=9, stroke_fill=(0, 0, 0))
                        x += dr.textlength(head + " ", font=f)
                    dr.text((x, y), words_last[-1], font=f, fill=(255, 214, 0), stroke_width=9, stroke_fill=(0, 0, 0))
                else:
                    dr.text((56, y), ln, font=f, fill=(255, 255, 255), stroke_width=9, stroke_fill=(0, 0, 0))
            y += lh

    im.paste(Image.new("RGB", im.size, (0, 0, 0)), (0, 0), shadow_layer(im.size, lambda dr, c: draw_text(dr, c), 14, 230))
    draw_text(d)
    pill(d, (56, y0 - 92), badge, font("Anton.ttf", 46, None), (230, 30, 40), (255, 255, 255), pad=(20, 10), radius=12)
    im.save(out, quality=92)
    return out


# ----------------------------------------------------------------- Calm Haven
CALM = {
    "regen": {"hooks": ["Fall Asleep Fast", "Deep Sleep Rain", "Instant Calm", "Rain to Sleep", "Let Go & Sleep"],
              "word": "RAIN SOUNDS", "grade": (0.95, 1.05, 1.12), "accent": (170, 210, 255)},
    "kamin": {"hooks": ["Cozy Night In", "Warm & Cozy", "Crackling Fire", "Slow Evening", "Cabin Calm"],
              "word": "FIREPLACE", "grade": (1.12, 1.0, 0.88), "accent": (255, 196, 120)},
    "wasserfall": {"hooks": ["Deep Focus", "Calm Your Mind", "Peaceful Stream", "Quiet Forest", "Pure Nature"],
                   "word": "WATER SOUNDS", "grade": (0.95, 1.06, 1.04), "accent": (150, 235, 215)},
}


def _grade(im, rgb):
    r, g, b = im.split()
    return Image.merge("RGB", [ch.point(lambda v, k=k: min(255, int(v * k))) for ch, k in zip((r, g, b), rgb)])


def calm(bg, channel, hours, hook, out):
    st = CALM[channel]
    im = cover(bg)
    im = ImageEnhance.Brightness(im).enhance(0.92)
    im = _grade(ImageEnhance.Contrast(im).enhance(1.1), st["grade"])
    im = vignette(im, 0.75, "bottom")
    im = vignette(im, 0.35)
    d = ImageDraw.Draw(im)
    f, lines, size = fit(d, hook, "PlayfairDisplay.ttf", 1080, 2, 132, 70)
    lh = int(size * 1.08)
    y = H - 175 - lh * len(lines)

    def draw_hook(dr, fill=None):
        yy = y
        for ln in lines:
            dr.text((W // 2, yy), ln, font=f, anchor="ma", fill=fill or (255, 250, 240))
            yy += lh

    im.paste(Image.new("RGB", im.size, (0, 0, 0)), (0, 0), shadow_layer(im.size, lambda dr, c: draw_hook(dr, c), 18, 210))
    draw_hook(d)
    label = f"{hours:g} HOUR{'S' if hours != 1 else ''}  ·  {st['word']}"
    fb = font("Montserrat.ttf", 40, "Bold")
    tw = d.textlength(label, font=fb)
    x = (W - tw) // 2 - 28
    box = [x, H - 128, x + tw + 56, H - 62]
    lay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(lay).rounded_rectangle(box, radius=33, fill=(10, 12, 18, 150), outline=st["accent"] + (255,), width=3)
    im.paste(lay, (0, 0), lay)
    d = ImageDraw.Draw(im)
    d.text((W // 2, (box[1] + box[3]) // 2), label, font=fb, anchor="mm", fill=st["accent"])
    im.save(out, quality=92)
    return out


def calm_hook(channel, rnd=random):
    return rnd.choice(CALM[channel]["hooks"])


# ----------------------------------------------------------------- Kinder
KIDS = {
    "schlaf": {"font": "Fredoka.ttf", "stroke": (70, 45, 130), "badge_bg": (255, 214, 90), "badge_fg": (70, 45, 130)},
    "geschichten": {"font": "Fredoka.ttf", "stroke": (150, 50, 90), "badge_bg": (255, 236, 160), "badge_fg": (150, 50, 90)},
}


def _star(d, cx, cy, r, fill):
    import math
    pts = []
    for i in range(10):
        a = math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        pts.append((cx + rr * math.cos(a), cy - rr * math.sin(a)))
    d.polygon(pts, fill=fill)


def kids(bg, channel, title, badge, out, rnd=random):
    st = KIDS[channel]
    im = cover(bg)
    im = ImageEnhance.Color(ImageEnhance.Brightness(im).enhance(1.06)).enhance(1.2)
    im = vignette(im, 0.45, "bottom")
    d = ImageDraw.Draw(im)
    f, lines, size = fit(d, title, st["font"], 1120, 2, 118, 64, variation="Bold")
    lh = int(size * 1.05)
    y = H - 60 - lh * len(lines)

    def draw_title(dr, fill=None):
        yy = y
        for ln in lines:
            if fill:
                dr.text((W // 2, yy + 6), ln, font=f, anchor="ma", fill=fill)
            else:
                dr.text((W // 2, yy), ln, font=f, anchor="ma", fill=(255, 255, 255), stroke_width=12, stroke_fill=st["stroke"])
            yy += lh

    im.paste(Image.new("RGB", im.size, (0, 0, 0)), (0, 0), shadow_layer(im.size, lambda dr, c: draw_title(dr, c), 10, 150))
    draw_title(d)
    lay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(lay)
    for _ in range(7):                                           # ein paar Sterne oben
        _star(ld, rnd.randint(40, W - 40), rnd.randint(30, 210), rnd.randint(9, 20), (255, 236, 150, 230))
    im.paste(lay, (0, 0), lay)
    d = ImageDraw.Draw(im)
    if badge:
        pill(d, (40, 36), badge, font("Fredoka.ttf", 50, "Bold"), st["badge_bg"], st["badge_fg"], pad=(26, 12))
    im.save(out, quality=92)
    return out
