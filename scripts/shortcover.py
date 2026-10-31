#!/usr/bin/env python3
"""
Titelbild für Shorts: YouTube zeigt bei Shorts im Feed meist ein Bild AUS dem Video – deshalb bekommt jedes Short in
den ersten ~2 Sekunden eine gestaltete Titelzeile (gleichzeitig ein stärkerer Einstieg). Zusätzlich wird daraus ein
Thumbnail-Bild gebaut, das per API gesetzt wird (wird z. B. in Suche/Kanalseite genutzt).

  new_video, thumb = shortcover.apply("short.mp4", "Rain on the window – instant calm #shorts", "regen")
"""
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

import thumbs

STYLE = {   # Schrift, Textfarbe, Konturfarbe, Großbuchstaben?
    "regen": ("PlayfairDisplay.ttf", (255, 250, 240), (0, 0, 0), False),
    "kamin": ("PlayfairDisplay.ttf", (255, 240, 215), (0, 0, 0), False),
    "wasserfall": ("PlayfairDisplay.ttf", (240, 255, 250), (0, 0, 0), False),
    "schlaf": ("Fredoka.ttf", (255, 255, 255), (70, 45, 130), False),
    "geschichten": ("Fredoka.ttf", (255, 255, 255), (150, 50, 90), False),
    "lernen": ("Cinzel.ttf", (255, 244, 220), (20, 10, 40), True),        # dear.zodiac
    "whatif": ("Anton.ttf", (255, 255, 255), (0, 0, 0), True),
    "gedanken": ("PlayfairDisplay.ttf", (250, 246, 236), (0, 0, 0), False),
}
HOLD, FADE = 1.8, 0.5


def channel_key(name):
    n = (name or "").lower()
    for pat, key in (("rain", "regen"), ("fire", "kamin"), ("water", "wasserfall"), ("mondmelodie", "schlaf"),
                     ("gute-nacht", "geschichten"), ("zodiac", "lernen"), ("beyond", "whatif"), ("gedanken", "gedanken")):
        if pat in n:
            return key
    return None


def clean(title):
    t = re.sub(r"#\S+", "", title)
    t = re.sub(r"[\U0001F000-\U0001FAFF☀-➿️]", "", t)
    return re.sub(r"\s+", " ", t).strip(" –-|·")


def card(text, channel, w, h):
    fname, fill, stroke, upper = STYLE.get(channel, STYLE["whatif"])
    text = text.upper() if upper else text
    lay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    var = None if fname == "Anton.ttf" else "Bold"
    f, lines, size = thumbs.fit(d, text, fname, int(w * 0.86), 4, int(w * 0.115), int(w * 0.055), variation=var)
    lh = int(size * 1.12)
    y0 = int(h * 0.30) - lh * len(lines) // 2
    sw = max(4, size // 11)
    shade = Image.new("RGBA", (w, h), (0, 0, 0, 0))                  # weicher dunkler Balken hinter dem Text
    ImageDraw.Draw(shade).rectangle([0, y0 - lh // 2, w, y0 + lh * len(lines) + lh // 3], fill=(0, 0, 0, 120))
    lay = Image.alpha_composite(lay, shade.filter(ImageFilter.GaussianBlur(40)))
    d = ImageDraw.Draw(lay)
    y = y0
    for i, ln in enumerate(lines):
        col = (255, 214, 0) if channel == "whatif" and i == len(lines) - 1 else fill
        d.text((w // 2, y), ln, font=f, anchor="ma", fill=col, stroke_width=sw, stroke_fill=stroke)
        y += lh
    return lay


def apply(video, title, channel):
    video = Path(video)
    text = clean(title)
    if not text or channel not in STYLE:
        return video, None
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                            "-of", "csv=p=0", str(video)], capture_output=True, text=True).stdout.strip().split(",")
    w, h = int(probe[0]), int(probe[1])
    png = video.with_name(video.stem + "_card.png")
    card(text, channel, w, h).save(png)
    out = video.with_name(video.stem + "_cover.mp4")
    flt = (f"[1:v]format=rgba,fade=t=out:st={HOLD}:d={FADE}:alpha=1[c];"
           f"[0:v][c]overlay=0:0:enable='lte(t,{HOLD + FADE})'[v]")
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-loop", "1", "-t", str(HOLD + FADE),
                        "-i", str(png), "-filter_complex", flt, "-map", "[v]", "-map", "0:a?", "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "copy",
                        "-movflags", "+faststart", str(out)], capture_output=True, text=True)
    if r.returncode or not out.exists():
        raise RuntimeError("Titelzeile: " + r.stderr[-300:])
    import shutil
    shutil.move(str(out), str(video))                 # Original ersetzen -> auch Instagram & Archiv bekommen die Titelzeile
    out = video
    thumb = video.with_name(video.stem + "_thumb.jpg")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.6", "-i", str(out), "-frames:v", "1", "-q:v", "2",
                    str(thumb)], check=False)
    return out, (thumb if thumb.exists() else None)
