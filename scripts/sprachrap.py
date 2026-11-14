#!/usr/bin/env python3
"""
„Französisch ist einfach, oder?“ – kurze Rap-Reels mit eigener Figur (Igel mit Baskenmütze).

  python scripts/sprachrap.py --episode 1 --out out/

Bilder + Mundstellungen (Qwen-Image/-Edit) und Stimme (Chatterbox Multilingual, DE + FR) auf Modal;
Mund bewegt sich nach Lautstärke der Stimme; Schnitt, Text und CC0-Beat hier.
"""
import argparse
import io
import json
import os
import subprocess
from pathlib import Path

import numpy as np
import requests
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
W, H, FPS, SR = 1080, 1920, 30, 24000
INK, PAPER = (52, 38, 28), (247, 236, 214)

STYLE = ("Cozy hand-drawn storybook illustration, soft colored pencil and gentle watercolor texture on warm cream paper, "
         "muted beige, sepia and warm brown tones, subtle grain. ")
HERO = ("a tiny chubby round hedgehog character with soft light-brown spines, a round cream-colored face, big sleepy "
        "half-closed eyes, small rosy cheeks, wearing a small red beret, big black over-ear headphones and an oversized "
        "mustard-yellow hoodie")
BASE = (STYLE + f"Vertical 9:16 picture. {HERO.capitalize()}, sitting at a wooden desk in front of a studio microphone on "
        "a small stand, paws resting on the desk, calm deadpan expression, facing the viewer. Cozy Parisian attic room: "
        "slanted wooden ceiling, small round window showing Paris rooftops at dusk, warm glowing desk lamp, plants, "
        "stacked books, small framed sketches on the wall. The character is centered in the lower half; the upper third "
        "is calm empty wall. Cute, gentle, minimal.")
SCENE_B = ("Show the same hedgehog character (same red beret, same black headphones, same mustard-yellow hoodie, same face) "
           "now sitting cross-legged on a cozy bed with a knitted blanket in the same Parisian attic room, playing a small "
           "black beat pad with colorful square buttons on his lap, facing the viewer. Same colored pencil storybook style, "
           "same warm lamp light. Character centered in the lower half, upper third calm empty wall.")
MOUTHS = [
    "Change only the character's mouth: mouth closed, a small calm line. Keep everything else exactly identical.",
    "Change only the character's mouth: mouth slightly open, as if saying a short word. Keep everything else exactly identical.",
    "Change only the character's mouth: mouth wide open, as if rapping a word loudly. Keep everything else exactly identical.",
]

# (Anzeige, Untertitel klein, gesprochener Text, Sprache, Szene, rap)
EPISODES = {
    1: {"title": "Teil 1", "lines": [
        ("Französisch ist einfach, oder?", "", "Französisch ist einfach, oder?", "de", "A", False),
        ("Wie sagt man „Wurm“ auf Französisch?", "", "Wie sagt man Wurm auf Französisch?", "de", "A", False),
        ("Ver.", "= Wurm", "Ver.", "fr", "B", False),
        ("Und „grün“?", "", "Und grün?", "de", "A", False),
        ("Vert.", "= grün", "Vert.", "fr", "B", False),
        ("„Glas“?", "", "Glas?", "de", "A", False),
        ("Verre.", "= Glas", "Verre.", "fr", "B", False),
        ("Und „Richtung“?", "", "Und Richtung?", "de", "A", False),
        ("Vers.", "= Richtung", "Vers.", "fr", "B", False),
        ("Klingt alles gleich. Pass auf:", "", "Klingt alles gleich. Pass auf!", "de", "A", False),
        ("Un ver vert va vers un verre vert.", "Ein grüner Wurm geht zu einem grünen Glas.",
         "Un ver vert va vers un verre vert.", "fr", "B", True),
        ("Un ver vert va vers un verre vert!", "", "Un ver vert, va vers un verre vert!", "fr", "B", True),
        ("Französisch ist einfach. Oder?", "", "Französisch ist einfach. Oder?", "de", "A", False),
    ], "caption": ("Französisch ist einfach, oder? 🇫🇷🎧 Teil 1\n\n"
                   "ver = Wurm · vert = grün · verre = Glas · vers = Richtung\n"
                   "👉 Un ver vert va vers un verre vert.\n(Ein grüner Wurm geht zu einem grünen Glas.)\n\n"
                   "Welches Wort sollen wir als Nächstes auseinandernehmen? 👇\n\n"
                   "#französischlernen #französisch #sprachenlernen #french #wortspiel #lernen")},
}


def font(size):
    from PIL import ImageFont
    for f in (ROOT / "fonts" / "Nunito.ttf", ROOT / "fonts" / "Fredoka.ttf", Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")):
        try:
            ft = ImageFont.truetype(str(f), size)
            try:
                ft.set_variation_by_axes([800])
            except Exception:  # noqa: BLE001
                pass
            return ft
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def mouth_mask(base, variants):
    """Bereich, den die Mund-Varianten tatsächlich verändern (größte zusammenhängende Fläche), weich ausgeblendet."""
    from PIL import Image, ImageFilter
    from scipy import ndimage
    b = np.asarray(base.convert("L"), dtype=np.int16)
    diff = np.zeros_like(b, dtype=bool)
    for v in variants:
        d = np.abs(np.asarray(v.convert("L"), dtype=np.int16) - b) > 38
        diff |= ndimage.binary_opening(d, iterations=2)
    lab, n = ndimage.label(ndimage.binary_dilation(diff, iterations=6))
    if n == 0:
        return None
    sizes = ndimage.sum(np.ones_like(lab), lab, range(1, n + 1))
    # nur Flächen in der unteren Bildhälfte-Mitte (Gesicht) berücksichtigen
    best, best_s = None, 0
    for i, s in enumerate(sizes, start=1):
        ys, xs = np.where(lab == i)
        cy, cx = ys.mean() / b.shape[0], xs.mean() / b.shape[1]
        if 0.3 < cy < 0.85 and 0.2 < cx < 0.8 and s > best_s:
            best, best_s = i, s
    if best is None:
        return None
    ys, xs = np.where(lab == best)
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    pad = 24
    m = np.zeros_like(b, dtype=np.uint8)
    m[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad] = 255
    print(f"Mundbereich: x {x0}-{x1}, y {y0}-{y1}")
    return Image.fromarray(m).filter(ImageFilter.GaussianBlur(14))


def beat(work: Path, seconds: float):
    key = os.environ.get("FREESOUND_API_KEY")
    if not key:
        return np.zeros(int(seconds * SR), dtype=np.float32)
    r = requests.get("https://freesound.org/apiv2/search/text/", timeout=30, params={
        "query": "lofi hip hop beat loop", "filter": 'license:"Creative Commons 0" duration:[20 TO 180]',
        "fields": "id,name,previews,tags,duration", "sort": "rating_desc", "page_size": 15, "token": key})
    for s in r.json().get("results", []):
        if {"vocal", "vocals", "voice", "singing", "rap"} & {t.lower() for t in s.get("tags", [])}:
            continue
        p = work / "beat.mp3"
        p.write_bytes(requests.get(s["previews"]["preview-hq-mp3"], timeout=60).content)
        print("Beat:", s["name"], s["id"])
        raw = subprocess.run(["ffmpeg", "-v", "error", "-stream_loop", "-1", "-i", str(p), "-t", f"{seconds:.2f}",
                              "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True, check=True).stdout
        a = np.frombuffer(raw, dtype=np.float32).copy()
        a /= max(1e-6, np.abs(a).max())
        return np.pad(a, (0, max(0, int(seconds * SR) - len(a))))
    return np.zeros(int(seconds * SR), dtype=np.float32)


def load_wav(b):
    a, sr = sf.read(io.BytesIO(b), dtype="float32")
    if a.ndim > 1:
        a = a.mean(1)
    if sr != SR:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "-", "-ar", str(SR),
                              "-f", "f32le", "-"], input=a.tobytes(), capture_output=True, check=True).stdout
        a = np.frombuffer(raw, dtype=np.float32).copy()
    nz = np.where(np.abs(a) > 0.02)[0]                  # Stille vorn/hinten abschneiden
    if len(nz):
        a = a[max(0, nz[0] - int(0.03 * SR)): nz[-1] + int(0.08 * SR)]
    return a / max(1e-6, np.abs(a).max()) * 0.9


def draw_text(im, big, small, frac):
    from PIL import ImageDraw
    d = ImageDraw.Draw(im)
    size = 74
    f = font(size)
    words, lines = big.split(), []
    while True:
        lines, cur = [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if d.textlength(t, font=f) > W - 150 and cur:
                lines.append(cur)
                cur = w
            else:
                cur = t
        lines.append(cur)
        if len(lines) <= 3 or size <= 50:
            break
        size -= 6
        f = font(size)
    y = int(H * 0.2)
    pop = min(1.0, frac * 6)                             # kurzes Einblenden
    col = tuple(int(PAPER[i] + (INK[i] - PAPER[i]) * pop) for i in range(3))
    for ln in lines:
        d.text((W // 2, y), ln, font=f, fill=col, anchor="ma", stroke_width=5, stroke_fill=PAPER)
        y += int(size * 1.22)
    if small:
        fs = font(44)
        d.text((W // 2, y + 18), small, font=fs, fill=(140, 72, 46), anchor="ma", stroke_width=4, stroke_fill=PAPER)


def build(ep_no, out: Path):
    from PIL import Image
    ep = EPISODES[ep_no]
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)
    ref = (ROOT / "data/voices/male_high.wav").read_bytes()
    cache = work / "art.json"
    import modal
    from sprachrap_modal import Art, Voice, app
    with modal.enable_output(), app.run():
        voice_call = Voice().speak_many.spawn([(l[2], l[3]) for l in ep["lines"]], ref)
        art = Art().make.remote(BASE, SCENE_B, MOUTHS)
        wavs = voice_call.get()
    for k in ("A", "B"):
        (work / f"{k}.png").write_bytes(art[k])
        for i, b in enumerate(art[f"{k}_m"]):
            (work / f"{k}_m{i}.png").write_bytes(b)
    cache.write_text(json.dumps({"ok": True}))

    # Figurbilder: Basis + 3 Mundstellungen, nur der Mundbereich wird aus der Variante übernommen
    scenes = {}
    for k in ("A", "B"):
        base = Image.open(work / f"{k}.png").convert("RGB")
        vars_ = [Image.open(work / f"{k}_m{i}.png").convert("RGB").resize(base.size) for i in range(3)]
        mask = mouth_mask(base, vars_)
        frames = [Image.composite(v, base, mask) if mask is not None else base for v in vars_]
        scale = W * 1.04 / base.width                     # etwas größer für sanften Zoom
        scenes[k] = [f.resize((int(base.width * scale), int(base.height * scale)), Image.LANCZOS) for f in frames]

    # Ton: Zeilen nacheinander, Rap-Zeilen dichter
    voice, spans, t = [], [], 0.6
    gap = lambda rap: 0.18 if rap else 0.42  # noqa: E731
    for line, wb in zip(ep["lines"], wavs):
        a = load_wav(wb)
        spans.append((t, t + len(a) / SR, line))
        voice.append((int(t * SR), a))
        t += len(a) / SR + gap(line[5])
    total = t + 1.2
    v = np.zeros(int(total * SR), dtype=np.float32)
    for s, a in voice:
        v[s:s + len(a)] += a
    mix = v + beat(work, total) * 0.16
    mix[-int(SR * 1.0):] *= np.linspace(1, 0, int(SR * 1.0))
    mix = (mix / max(1.0, np.abs(mix).max()) * 0.95).astype(np.float32)
    sf.write(work / "mix.wav", mix, SR)

    # Mundöffnung je Bild aus der Lautstärke
    hop = SR // FPS
    env = np.array([np.sqrt(np.mean(v[i * hop:(i + 1) * hop] ** 2) + 1e-9) for i in range(int(total * FPS))])
    env = np.convolve(env, np.ones(2) / 2, "same")
    lvl = np.where(env > 0.16, 2, np.where(env > 0.05, 1, 0))

    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                             "-r", str(FPS), "-i", "-", "-i", str(work / "mix.wav"), "-c:v", "libx264", "-preset", "medium",
                             "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-shortest",
                             "-movflags", "+faststart", str(out / f"sprachrap_{ep_no:02d}.mp4")], stdin=subprocess.PIPE)
    n = int(total * FPS)
    for i in range(n):
        ts = i / FPS
        cur = next((s for s in spans if s[0] - 0.05 <= ts < s[1] + gap(s[2][5])), None) or (spans[-1] if ts > spans[-1][0] else spans[0])
        line = cur[2]
        img = scenes[line[4]][int(lvl[i])]
        z = 1.0 + 0.012 * np.sin(ts * 2 * np.pi / 6)      # langsames Atmen
        cw, ch = int(W / z * 1.0), int(H / z * 1.0)
        ox = (img.width - cw) // 2
        oy = max(0, min(img.height - ch, (img.height - ch) // 2))
        fr = img.crop((ox, oy, ox + cw, oy + ch)).resize((W, H))
        if ts < spans[0][0] - 0.05:
            draw_text(fr, ep["title"], "", 1.0)
        else:
            draw_text(fr, line[0], line[1], (ts - cur[0]) / 1.0)
        proc.stdin.write(fr.tobytes())
    proc.stdin.close()
    proc.wait()
    (out / f"sprachrap_{ep_no:02d}.txt").write_text(ep["caption"], encoding="utf-8")
    print(f"::notice title=Sprachrap::Folge {ep_no}: {total:.1f} s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", type=int, default=1)
    ap.add_argument("--out", default="out")
    a = ap.parse_args()
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    build(a.episode, Path(a.out).resolve())
