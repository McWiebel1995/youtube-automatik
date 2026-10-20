"""
Shorts (Hochformat 1080x1920, unter 60 s) für Kanäle ohne Freischaltung langer Videos.

  schlaf_short(): Spieluhr-Short für Mondmelodie – Sternenhimmel hochkant, neues Schlaflied,
                  sanfter Gute-Nacht-Text.
"""
import os
import subprocess
import sys
from pathlib import Path

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402
from scipy.io import wavfile  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drawing  # noqa: E402
import music  # noqa: E402


def _portrait_visuals():
    """Eigene Kopie von visuals.py, die hochkant (540x960) zeichnet – die Querformat-Szenen bleiben unberührt."""
    import importlib.util
    old = os.environ.get("KIDS_VIS_W"), os.environ.get("KIDS_VIS_H")
    os.environ["KIDS_VIS_W"], os.environ["KIDS_VIS_H"] = "540", "960"
    try:
        spec = importlib.util.spec_from_file_location("visuals_portrait", Path(__file__).with_name("visuals.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        for k, v in zip(("KIDS_VIS_W", "KIDS_VIS_H"), old):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return mod


visuals = _portrait_visuals()

W, H, FPS = 1080, 1920, 24

GREETINGS = [
    ("Gute Nacht", "Schlaf schön, kleiner Stern"),
    ("Schlaf gut", "Der Mond passt auf dich auf"),
    ("Süße Träume", "Die Sterne leuchten für dich"),
    ("Gute Nacht", "Kuschel dich ein und träum was Schönes"),
    ("Psst …", "Zeit zum Schlafen"),
]


def text_layer(title, sub, footer):
    """Transparente Textebene (RGBA) mit weichem Leuchten."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def centered(text, size, y, fill, weight="SemiBold", family="Quicksand"):
        f = drawing.font(size, weight, family)
        tw = d.textlength(text, font=f)
        d.text(((W - tw) / 2, y), text, font=f, fill=fill)

    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    f = drawing.font(150, "Regular", "Pacifico")
    tw = gd.textlength(title, font=f)
    gd.text(((W - tw) / 2, 640), title, font=f, fill=(255, 230, 160, 200))
    glow = glow.filter(ImageFilter.GaussianBlur(18))
    img = Image.alpha_composite(img, glow)
    d = ImageDraw.Draw(img)
    centered(title, 150, 640, (255, 246, 220, 255), "Regular", "Pacifico")
    # Untertitel ggf. umbrechen
    words, lines, cur = sub.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if d.textlength(test, font=drawing.font(70, "SemiBold", "Quicksand")) > W - 160 and cur:
            lines.append(cur)
            cur = w
        else:
            cur = test
    lines.append(cur)
    for i, ln in enumerate(lines):
        centered(ln, 70, 860 + i * 90, (225, 225, 255, 235), "SemiBold")
    centered(footer, 42, 1800, (200, 200, 235, 200), "SemiBold")
    return img


def schlaf_short(work: Path, rnd, seconds=45.0):
    work.mkdir(parents=True, exist_ok=True)
    seed = rnd.randrange(2**31)
    rng = np.random.default_rng(seed)

    # Musik: ein neues Schlaflied, auf Länge gekürzt mit weichem Ausklang
    y = music.lullaby(seed, repeats=2)
    n = int(seconds * music.SR)
    if len(y) < n:
        y = np.concatenate([y, np.zeros((n - len(y), 2))])
    y = y[:n].copy()
    fi, fo = int(1.0 * music.SR), int(4.0 * music.SR)
    y[:fi] *= np.linspace(0, 1, fi)[:, None]
    y[-fo:] *= np.linspace(1, 0, fo)[:, None]
    wav = work / "music.wav"
    wavfile.write(str(wav), music.SR, (np.clip(y, -1, 1) * 32767).astype(np.int16))

    # Bild: Sternenhimmel hochkant (mit Haus & Glühwürmchen in der Hälfte der Fälle)
    title, sub = rnd.choice(GREETINGS)
    overlay = work / "text.png"
    text_layer(title, sub, "Mehr Einschlafmusik auf dem Kanal").save(overlay)
    scene = visuals.nachthimmel(rng, seconds, house=rnd.random() < 0.5)
    out = work / "video.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{visuals.W}x{visuals.H}", "-r", str(FPS), "-i", "-",
           "-loop", "1", "-i", str(overlay), "-i", str(wav),
           "-filter_complex",
           f"[0:v]scale={W}:{H}:flags=lanczos[bg];"
           f"[1:v]format=rgba,fade=t=in:st=1.5:d=2:alpha=1,fade=t=out:st={seconds - 3.5}:d=2.5:alpha=1[tx];"
           f"[bg][tx]overlay=0:0:shortest=1,fade=t=out:st={seconds - 1.5}:d=1.5,format=yuv420p[v]",
           "-map", "[v]", "-map", "2:a", "-t", f"{seconds}",
           "-c:v", "libx264", "-profile:v", "high", "-preset", "medium", "-crf", "19",
           "-c:a", "aac", "-b:a", "192k", "-af", "loudnorm=I=-18:TP=-2", "-movflags", "+faststart", str(out)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(int(seconds * FPS)):
        p.stdin.write(np.clip(scene(i / FPS), 0, 255).astype(np.uint8).tobytes())
    p.stdin.close()
    if p.wait():
        raise RuntimeError("ffmpeg-Fehler beim Schlaf-Short")
    return {"video_file": str(out), "title_word": title, "subtitle": sub, "seconds": seconds, "music_seed": seed}


if __name__ == "__main__":
    import random
    info = schlaf_short(Path(sys.argv[1] if len(sys.argv) > 1 else "output/test-schlaf-short"),
                        random.Random(int(sys.argv[2]) if len(sys.argv) > 2 else None))
    print(info)
