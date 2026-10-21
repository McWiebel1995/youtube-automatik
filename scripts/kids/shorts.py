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
        if d.textlength(test, font=drawing.font(66, "Bold", "Quicksand")) > W - 160 and cur:
            lines.append(cur)
            cur = w
        else:
            cur = test
    lines.append(cur)
    for i, ln in enumerate(lines):
        centered(ln, 66, 920 + i * 86, (230, 230, 255, 240), "Bold")
    centered(footer, 42, 1800, (205, 205, 240, 215), "Bold")
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


# ----------------------------------------------------------------- Mini-Geschichte (Gute-Nacht-Kiste)
def story_short(title, text, work: Path, rnd, voice, rate, max_seconds=58.0, gvoice=None):
    """Hochkant-Short: Bilderbuch-Nachtszene, Sprecherstimme, große Untertitel, Titel oben."""
    import re as _re

    from scipy.signal import resample_poly

    import tts

    work.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[2]
    SR = music.SR
    sents = [s for s in _re.split(r"(?<=[.!?])\s+", text.strip()) if s]
    pieces, subs, t = None, [], 1.2
    if gvoice and os.environ.get("GEMINI_API_KEY"):
        try:
            sys.path.insert(0, str(root / "scripts"))
            import gtts
            audio, subs, _ = gtts.spoken_with_timing([text], gvoice, work, SR,
                                                     lambda x: [s for s in _re.split(r"(?<=[.!?])\s+", x.strip()) if s],
                                                     lead=1.2)
            pieces = [audio]
            t = len(audio) / SR
            subs = [(a, min(b, max_seconds - 2.5), x) for a, b, x in subs if a < max_seconds - 2.5]
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ Gemini-Stimme (Short) nicht verfügbar: {str(e)[:160]}")
            pieces, subs, t = None, [], 1.2
    if pieces is None:
        pieces = [np.zeros(int(1.2 * SR), np.float32)]
        for i, s in enumerate(sents):
            wav = work / f"m_{i:02d}.wav"
            tts.speak(s, wav, voice, rate)
            sr, a = wavfile.read(wav)
            a = a.astype(np.float32) / 32768
            if a.ndim > 1:
                a = a.mean(axis=1)
            if sr != SR:
                a = resample_poly(a, SR, sr).astype(np.float32)
            d = len(a) / SR
            if t + d > max_seconds - 2.5:
                break
            subs.append((t, t + d + 0.3, s))
            pieces += [a, np.zeros(int(0.45 * SR), np.float32)]
            t += d + 0.45
            wav.unlink(missing_ok=True)
    seconds = min(max_seconds, t + 2.5)
    voice_trk = np.concatenate(pieces)
    voice_trk = np.pad(voice_trk, (0, max(0, int(seconds * SR) - len(voice_trk))))[: int(seconds * SR)]
    m = music.lullaby(rnd.randrange(2**31), repeats=2, bpm=(48, 58))
    m = np.pad(m, ((0, max(0, len(voice_trk) - len(m))), (0, 0)))[: len(voice_trk)] * (10 ** (-22 / 20))
    mix = np.stack([voice_trk * 1.4, voice_trk * 1.4], 1) + m
    fo = int(2.0 * SR)
    mix[-fo:] *= np.linspace(1, 0, fo)[:, None]
    wav = work / "mix.wav"
    wavfile.write(str(wav), SR, (np.clip(mix, -1, 1) * 32767).astype(np.int16))

    fdir = root / "assets" / "fonts"
    sub_font = "Nunito" if (fdir / "Nunito.ttf").exists() else "DejaVu Sans"
    title_font = "Baloo 2" if (fdir / "Baloo2.ttf").exists() else sub_font

    def ts(x):
        h, r = divmod(x, 3600)
        mm, ss = divmod(r, 60)
        return f"{int(h)}:{int(mm):02d}:{ss:05.2f}"

    def esc(x):
        return x.replace("{", "(").replace("}", ")").replace("\n", " ")
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 0\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
            "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
            "MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Sub,{sub_font},64,&H00F5F5FF,&H000000FF,&H00402020,&H78000000,1,0,0,0,100,100,0,0,1,4,2,5,90,90,0,1\n"
            f"Style: Kicker,{title_font},68,&H00A0E6FF,&H000000FF,&H00402020,&H64000000,1,0,0,0,100,100,0,0,1,4,2,8,80,80,170,1\n"
            f"Style: Title,{title_font},150,&H00D8F4FF,&H000000FF,&H00402020,&H64000000,1,0,0,0,100,100,0,0,1,5,2,8,80,80,250,1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    ev = [f"Dialogue: 0,{ts(0)},{ts(seconds)},Kicker,,0,0,0,,{{\\fad(600,600)}}Mini-Gute-Nacht-Geschichte",
          f"Dialogue: 0,{ts(0)},{ts(seconds)},Title,,0,0,0,,{{\\fad(600,600)}}{esc(title)}"]
    ev += [f"Dialogue: 0,{ts(a)},{ts(b)},Sub,,0,0,0,,{{\\fad(200,200)\\pos(540,1180)}}{esc(x)}" for a, b, x in subs]
    (work / "mini.ass").write_text(head + "\n".join(ev) + "\n", encoding="utf-8")

    rng = np.random.default_rng(rnd.randrange(2**31))
    scene = visuals.bilderbuch(rng, seconds)
    out = work / "video.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{visuals.W}x{visuals.H}", "-r", str(FPS), "-i", "-",
           "-i", str(wav), "-filter_complex",
           f"[0:v]scale={W}:{H}:flags=lanczos,subtitles=mini.ass:fontsdir='{fdir.as_posix()}',"
           f"fade=t=in:d=0.6,fade=t=out:st={seconds - 1.2}:d=1.2,format=yuv420p[v]",
           "-map", "[v]", "-map", "1:a", "-t", f"{seconds:.2f}",
           "-c:v", "libx264", "-profile:v", "high", "-preset", "medium", "-crf", "19",
           "-c:a", "aac", "-b:a", "192k", "-af", "loudnorm=I=-16:TP=-1.5", "-movflags", "+faststart", "video.mp4"]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, cwd=work)
    for i in range(int(seconds * FPS)):
        p.stdin.write(np.clip(scene(i / FPS), 0, 255).astype(np.uint8).tobytes())
    p.stdin.close()
    if p.wait():
        raise RuntimeError("ffmpeg-Fehler beim Geschichten-Short")
    return {"video_file": str(out), "seconds": round(seconds, 1), "title": title}
