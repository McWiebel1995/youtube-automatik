"""
Lernkanal: Zahlen, Farben und Formen – als langes Video (16:9) oder Short (9:16).
Alles wird selbst gezeichnet und vertont; Sprecherstimme per Piper.
"""
import math
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.io import wavfile
from scipy.signal import resample_poly

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import ffmpeg  # noqa: E402

import drawing as dr  # noqa: E402
import music  # noqa: E402
import tts  # noqa: E402

FPS = 30
SR = 44100

COLORS = [
    ("rot", "Rot", (229, 57, 53), "wie eine Erdbeere"),
    ("blau", "Blau", (30, 136, 229), "wie der Himmel"),
    ("gelb", "Gelb", (253, 216, 53), "wie die Sonne"),
    ("grün", "Grün", (67, 160, 71), "wie das Gras"),
    ("orange", "Orange", (251, 140, 0), "wie eine Karotte"),
    ("lila", "Lila", (142, 36, 170), "wie eine Pflaume"),
    ("rosa", "Rosa", (244, 143, 177), "wie ein kleines Schweinchen"),
    ("braun", "Braun", (121, 85, 72), "wie Schokolade"),
    ("weiß", "Weiß", (250, 250, 250), "wie ein Schneemann"),
    ("schwarz", "Schwarz", (40, 40, 52), "wie die Nacht"),
    ("grau", "Grau", (158, 158, 158), "wie ein Elefant"),
]

SHAPES = [
    ("kreis", "Kreis", "ein", "Ein Kreis ist ganz rund – wie ein Ball."),
    ("quadrat", "Quadrat", "ein", "Ein Quadrat hat vier gleich lange Seiten."),
    ("dreieck", "Dreieck", "ein", "Ein Dreieck hat drei Ecken."),
    ("rechteck", "Rechteck", "ein", "Ein Rechteck hat zwei lange und zwei kurze Seiten."),
    ("stern", "Stern", "ein", "Ein Stern hat fünf Zacken."),
    ("herz", "Herz", "ein", "Ein Herz – so sieht Liebhaben aus."),
    ("oval", "Oval", "ein", "Ein Oval ist rund und lang – wie ein Ei."),
    ("raute", "Raute", "eine", "Eine Raute sieht aus wie ein Drachen."),
    ("sechseck", "Sechseck", "ein", "Ein Sechseck hat sechs Ecken – wie eine Bienenwabe."),
]
SHAPE_COLORS = [(229, 57, 53), (30, 136, 229), (253, 216, 53), (67, 160, 71), (251, 140, 0),
                (142, 36, 170), (244, 143, 177), (0, 172, 193)]

NUM = ["null", "eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun", "zehn"]
NUM_ADJ = ["", "Ein", "Zwei", "Drei", "Vier", "Fünf", "Sechs", "Sieben", "Acht", "Neun", "Zehn"]

BACKGROUNDS = [((255, 241, 214), (255, 214, 224)), ((214, 240, 255), (226, 214, 255)),
               ((220, 255, 228), (255, 247, 205)), ((255, 228, 240), (214, 236, 255))]


def S(text, scene, pause=0.6, pop=False):
    return dict(text=text, scene=scene, pause=pause, pop=pop)


# ----------------------------------------------------------------- Drehbücher
def plan_farben(rnd, short=False):
    items = rnd.sample(COLORS, 3 if short else 9)
    segs = []
    if short:
        segs.append(S("Welche Farbe ist das?", dict(kind="color", c=items[0], ex=True, name=False, q=True), 2.2))
        first = True
    else:
        segs.append(S("Hallo! Heute lernen wir Farben. Bist du bereit? Los geht's!",
                      dict(kind="title", title="Farben lernen", sub="🌈"), 0.8))
        first = False
    for i, c in enumerate(items):
        if not (short and i == 0 and first):
            segs.append(S(f"Das ist {c[1]}.", dict(kind="color", c=c, ex=False, name=True), 0.5, pop=True))
        else:
            segs.append(S(f"{c[1]}!", dict(kind="color", c=c, ex=True, name=True), 0.4, pop=True))
        segs.append(S(f"{c[1]} – {c[3]}!", dict(kind="color", c=c, ex=True, name=True), 0.9))
    if not short:
        segs.append(S("Jetzt bist du dran! Welche Farbe hat das?", dict(kind="title", title="Quiz", sub="?"), 0.6))
        for c in rnd.sample(items, 4):
            segs.append(S("Welche Farbe ist das?", dict(kind="color", c=c, ex=True, name=False, q=True), 3.0))
            segs.append(S(f"Richtig! Das ist {c[1]}.", dict(kind="color", c=c, ex=True, name=True), 0.8, pop=True))
    segs.append(S("Toll gemacht! Bis zum nächsten Mal. Tschüss!" if not short else "Super gemacht!",
                  dict(kind="title", title="Toll gemacht!", sub="⭐"), 1.2))
    return segs, [c[1] for c in items]


def plan_formen(rnd, short=False):
    items = rnd.sample(SHAPES, 3 if short else 8)
    cols = rnd.sample(SHAPE_COLORS, len(items))
    segs = []
    if not short:
        segs.append(S("Hallo! Heute lernen wir Formen. Schau mal genau hin!",
                      dict(kind="title", title="Formen lernen", sub="⭐"), 0.8))
    for (k, name, art, desc), col in zip(items, cols):
        segs.append(S(f"Das ist {art} {name}.", dict(kind="shape", s=k, name=name, col=col, show=True), 0.5, pop=True))
        segs.append(S(desc, dict(kind="shape", s=k, name=name, col=col, show=True), 0.9))
    if not short:
        segs.append(S("Jetzt bist du dran! Wie heißt diese Form?", dict(kind="title", title="Quiz", sub="?"), 0.6))
        for (k, name, art, _), col in rnd.sample(list(zip(items, cols)), 4):
            segs.append(S("Wie heißt diese Form?", dict(kind="shape", s=k, name=name, col=col, show=False), 3.0))
            segs.append(S(f"Richtig! Das ist {art} {name}.", dict(kind="shape", s=k, name=name, col=col, show=True),
                          0.8, pop=True))
    segs.append(S("Toll gemacht! Bis zum nächsten Mal. Tschüss!" if not short else "Super gemacht!",
                  dict(kind="title", title="Toll gemacht!", sub="⭐"), 1.2))
    return segs, [i[1] for i in items]


def plan_zahlen(rnd, short=False):
    thing_key = rnd.choice(list(dr.THINGS))
    thing = dr.THINGS[thing_key]
    mx = rnd.randint(3, 6) if short else rnd.choice([5, 10])
    cols = [rnd.choice(SHAPE_COLORS) for _ in range(10)]
    segs = []
    if short:
        segs.append(S(f"Wir zählen {thing['many']}! Zählst du mit?",
                      dict(kind="count", n=mx, k=0, t=thing_key, cols=cols, num=False), 0.5))
        ns = [mx]
    else:
        segs.append(S(f"Hallo! Heute zählen wir {thing['many']}. Zählst du mit?",
                      dict(kind="title", title=f"Zählen bis {mx}", sub="🎈"), 0.8))
        ns = range(1, mx + 1)
    for n in ns:
        if not short:
            segs.append(S(f"Die Zahl {NUM[n]}.", dict(kind="count", n=n, k=0, t=thing_key, cols=cols, num=True), 0.4, pop=True))
        for k in range(1, n + 1):
            segs.append(S(f"{NUM[k].capitalize()}.", dict(kind="count", n=n, k=k, t=thing_key, cols=cols, num=short and k == n or not short),
                          0.25, pop=True))
        word = thing["one"] if n == 1 else thing["many"]
        segs.append(S(f"{NUM_ADJ[n]} {word}!", dict(kind="count", n=n, k=n, t=thing_key, cols=cols, num=True), 0.8))
    if not short:
        segs.append(S(f"Jetzt bist du dran! Wie viele {thing['many']} siehst du?",
                      dict(kind="title", title="Quiz", sub="?"), 0.6))
        for n in rnd.sample(range(2, mx + 1), min(4, mx - 1)):
            segs.append(S(f"Wie viele {thing['many']} sind das?",
                          dict(kind="count", n=n, k=n, t=thing_key, cols=cols, num=False), 3.5))
            segs.append(S(f"Richtig! Es sind {NUM[n]}.", dict(kind="count", n=n, k=n, t=thing_key, cols=cols, num=True),
                          0.8, pop=True))
    segs.append(S("Toll gezählt! Bis zum nächsten Mal. Tschüss!" if not short else "Super gezählt!",
                  dict(kind="title", title="Toll gemacht!", sub="⭐"), 1.2))
    return segs, dict(max=mx, things=thing["many"], n=mx)


PLANS = {"farben": plan_farben, "formen": plan_formen, "zahlen": plan_zahlen}


# ----------------------------------------------------------------- Zeichnen
class Renderer:
    def __init__(self, W, H, rnd):
        self.W, self.H, self.portrait = W, H, H > W
        top, bot = rnd.choice(BACKGROUNDS)
        t = np.linspace(0, 1, H)[:, None, None]
        bg = (np.array(top) * (1 - t) + np.array(bot) * t).repeat(W, axis=1).astype(np.uint8)
        self.bg = Image.fromarray(bg)
        self.bubbles = [(rnd.uniform(0, W), rnd.uniform(0, H), rnd.uniform(20, 90), rnd.uniform(0.1, 0.4),
                         rnd.uniform(0, 6.28)) for _ in range(14)]
        self.u = min(W, H) / 1080  # Maßeinheit

    def frame(self, seg, lt, t):
        img = self.bg.copy()
        d = ImageDraw.Draw(img)
        for x, y, r, sp, ph in self.bubbles:
            yy = (y - sp * 60 * t) % (self.H + 200) - 100
            xx = x + 20 * math.sin(t * 0.7 + ph)
            d.ellipse([xx - r, yy - r, xx + r, yy + r], outline=(255, 255, 255), width=3)
        sc = seg["scene"]
        getattr(self, "draw_" + sc["kind"])(d, sc, lt, t)
        return img

    def pop(self, lt, delay=0.0):
        return dr.ease_back((lt - delay) / 0.35)

    def draw_title(self, d, sc, lt, t):
        u, W, H = self.u, self.W, self.H
        s = self.pop(lt)
        dr.label(d, sc["title"], W / 2, H * 0.45, int(120 * u * max(0.2, s)), color=(90, 60, 140))
        for i in range(5):
            a = t * 0.8 + i * 2 * math.pi / 5
            cx, cy = W / 2 + math.cos(a) * W * 0.36, H * 0.45 + math.sin(a) * H * 0.3
            d.polygon(dr.star_points(cx, cy, 34 * u), fill=SHAPE_COLORS[i % len(SHAPE_COLORS)])

    def draw_color(self, d, sc, lt, t):
        u, W, H = self.u, self.W, self.H
        key, name, rgb, _ = sc["c"]
        s = self.pop(lt) if not sc.get("q") else 1
        wob = 1 + 0.02 * math.sin(t * 3)
        if self.portrait:
            blob, ex, lab = (W / 2, H * 0.27), (W / 2, H * 0.55), (W / 2, H * 0.8)
        else:
            blob, ex, lab = (W * 0.3, H * 0.44), (W * 0.7, H * 0.44), (W / 2, H * 0.83)
        if sc.get("q"):
            ex = (W / 2, H * 0.45)
            dr.COLOR_EXAMPLES[key](d, ex[0], ex[1], 200 * u * wob, rgb)
            dr.label(d, "?", lab[0], lab[1], int(110 * u), color=(90, 60, 140))
            return
        r = 210 * u * s * wob
        d.ellipse([blob[0] - r, blob[1] - r, blob[0] + r, blob[1] + r], fill=rgb, outline=dr.darker(rgb), width=int(8 * u))
        dr.face(d, blob[0], blob[1], r * 0.8, blink=(t % 4) < 0.15)
        if sc["ex"]:
            dr.COLOR_EXAMPLES[key](d, ex[0], ex[1], 160 * u * self.pop(lt, 0.15 if sc["name"] else 0), rgb)
        if sc["name"]:
            dr.label(d, name, lab[0], lab[1], int(110 * u), color=dr.darker(rgb, 0.8) if key != "weiß" else (120, 120, 140))

    def draw_shape(self, d, sc, lt, t):
        u, W, H = self.u, self.W, self.H
        s = self.pop(lt) if sc["show"] else 1
        wob = 1 + 0.03 * math.sin(t * 2.5)
        cy = H * (0.42 if self.portrait else 0.42)
        r = 260 * u * s * wob
        dr.shape(d, sc["s"], W / 2, cy, r, sc["col"])
        dr.face(d, W / 2, cy + r * 0.05, r * 0.45, blink=(t % 5) < 0.15)
        txt = sc["name"] if sc["show"] else "?"
        dr.label(d, txt, W / 2, H * (0.78 if self.portrait else 0.85), int(105 * u), color=dr.darker(sc["col"], 0.7))

    def draw_count(self, d, sc, lt, t):
        u, W, H = self.u, self.W, self.H
        n, k = sc["n"], sc["k"]
        thing = dr.THINGS[sc["t"]]
        if self.portrait:
            num_c = (W / 2, H * 0.17)
            cols, area = 3, (W * 0.08, H * 0.32, W * 0.92, H * 0.92)
        else:
            num_c = (W * 0.2, H * 0.5)
            cols, area = 5, (W * 0.38, H * 0.18, W * 0.96, H * 0.86)
        if sc["num"]:
            r = 150 * u
            d.ellipse([num_c[0] - r, num_c[1] - r, num_c[0] + r, num_c[1] + r], fill=(255, 255, 255),
                      outline=(90, 60, 140), width=int(8 * u))
            d.text(num_c, str(k if k else n), font=dr.font(int(190 * u)), fill=(90, 60, 140), anchor="mm")
        cols = min(cols, max(n, 1))
        rows = math.ceil(max(n, 1) / cols)
        cw = (area[2] - area[0]) / cols
        ch = (area[3] - area[1]) / rows
        rr = min(cw * 0.34, ch * 0.3, 150 * u)
        for i in range(k):
            row, col = divmod(i, cols)
            in_row = min(cols, n - row * cols)
            x0 = area[0] + (cols - in_row) * cw / 2
            cx = x0 + (col + 0.5) * cw
            cy = area[1] + (row + 0.5) * ch
            s = self.pop(lt) if i == k - 1 else 1
            bob = math.sin(t * 2 + i) * 6 * u
            thing["draw"](d, cx, cy + bob - rr * 0.3, rr * s, sc["cols"][i % len(sc["cols"])])


# ----------------------------------------------------------------- Ton
def pop_sound(rng):
    t = np.arange(int(0.12 * SR)) / SR
    f = 600 + 900 * t / t[-1]
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.04) * 0.25


def build_audio(segs, work, voice, rate, rnd):
    rng = np.random.default_rng(rnd.randrange(2**31))
    pieces, times, t = [], [], 0.6
    lead = np.zeros(int(0.6 * SR))
    pieces.append(lead)
    for i, seg in enumerate(segs):
        wav = work / f"seg_{i:03d}.wav"
        dur = tts.speak(seg["text"], wav, voice, rate)
        sr, data = wavfile.read(wav)
        data = data.astype(np.float32) / 32768
        if data.ndim > 1:
            data = data.mean(axis=1)
        if sr != SR:
            data = resample_poly(data, SR, sr).astype(np.float32)
        if seg["pop"]:
            p = pop_sound(rng)
            pad = np.zeros(len(p))
            data = np.concatenate([data, pad]) if len(data) < len(p) else data
            data[: len(p)] += p
        times.append(t)
        pieces.append(data)
        pieces.append(np.zeros(int(seg["pause"] * SR)))
        t += len(data) / SR + seg["pause"]
        wav.unlink(missing_ok=True)
    voice_track = np.concatenate(pieces + [np.zeros(int(1.0 * SR))])
    path = work / "voice.wav"
    wavfile.write(path, SR, (np.clip(voice_track, -1, 1) * 32767).astype(np.int16))
    return path, times, len(voice_track) / SR


def background_music(seconds, work, rnd):
    y = music.lullaby(rnd.randrange(2**31), repeats=1, bpm=(92, 112))
    path = work / "music.wav"
    wavfile.write(path, SR, (np.clip(y, -1, 1) * 32767).astype(np.int16))
    return path


# ----------------------------------------------------------------- Hauptfunktion
def produce(ch, topic, short, work: Path, rnd, voice, rate):
    work.mkdir(parents=True, exist_ok=True)
    segs, info = PLANS[topic](rnd, short)
    voice_wav, times, total = build_audio(segs, work, voice, rate, rnd)
    music_wav = background_music(total, work, rnd)

    W, H = (1080, 1920) if short else (1920, 1080)
    R = Renderer(W, H, rnd)
    silent = work / "silent.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "21",
           "-pix_fmt", "yuv420p", str(silent)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    idx = 0
    for f in range(int(total * FPS)):
        t = f / FPS
        while idx + 1 < len(times) and t >= times[idx + 1]:
            idx += 1
        lt = t - times[idx]
        p.stdin.write(R.frame(segs[idx], lt, t).tobytes())
    p.stdin.close()
    if p.wait():
        raise RuntimeError("ffmpeg-Fehler beim Lernvideo")

    out = work / "video.mp4"
    ffmpeg("-i", silent, "-i", voice_wav, "-stream_loop", "-1", "-i", music_wav,
           "-filter_complex",
           "[2:a]volume=-21dB[m];[1:a]volume=1.6[v];[v][m]amix=inputs=2:normalize=0:duration=first,"
           "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=44100[a]",
           "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
           "-shortest", "-movflags", "+faststart", out)
    for f_ in (silent, voice_wav, music_wav):
        f_.unlink(missing_ok=True)
    return {"video_file": str(out), "topic": topic, "short": short, "items": info, "seconds": round(total, 1),
            "script": [s["text"] for s in segs]}


def metadata(ch, info, rnd):
    topic, items = info["topic"], info["items"]
    if info["short"]:
        if topic == "zahlen":
            title = ch["short_titles"]["zahlen"].format(n=items["n"])
        else:
            title = ch["short_titles"][topic].format(item=items[0])
    else:
        tpl = rnd.choice(ch["title_templates"][topic])
        if topic == "zahlen":
            title = tpl.format(max=items["max"], things=items["things"])
        else:
            title = tpl.format(count=len(items), things=rnd.choice(["Spaß", "Liedern", "Bildern"]))
    script = "\n".join(f"• {s}" for s in info["script"][:12])
    desc = "\n".join([
        {"zahlen": "Gemeinsam zählen lernen – mit bunten Bildern und einer ruhigen Stimme.",
         "farben": "Farben spielerisch kennenlernen – mit Beispielen aus dem Alltag und einem kleinen Quiz.",
         "formen": "Kreis, Dreieck, Stern & Co. – Formen spielerisch kennenlernen mit Quiz."}[topic],
        "",
        "Für Kinder ab ca. 2 Jahren. Am schönsten gemeinsam mit Mama, Papa oder Geschwistern anschauen",
        "und laut mitsprechen!",
        "",
        "Inhalt:",
        script,
        "",
        "Alle Bilder, Melodien und Texte wurden für diesen Kanal erstellt.",
    ])
    return {"title": title[:100], "description": desc, "tags": ch["tags"], "scene": topic}
