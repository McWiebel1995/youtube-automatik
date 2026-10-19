#!/usr/bin/env python3
"""
Erzeugt nahtlose Video-Loops (Standard 12 s, 1080p) komplett selbst:
  regen      -> nasses Fenster bei Nacht mit Lichtern (Bokeh) und Regenstreifen
  kamin      -> flackerndes Kaminfeuer mit Glut und Funken
  wasserfall -> fallendes Wasser zwischen Felsen mit Nebel

Jede Variante bekommt eigene Farben, Formen und Bewegungen.

Beispiel:
    python scripts/gen_video.py --variants 3
"""
import argparse
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
W, H = 960, 540          # intern gerendert, danach weich auf 1920x1080 skaliert
FPS = 24


# ----------------------------------------------------------------- Hilfen
def gradient(top, bottom):
    t = np.linspace(0, 1, H)[:, None, None]
    g = np.array(top)[None, None, :] * (1 - t) + np.array(bottom)[None, None, :] * t
    return np.repeat(g, W, axis=1).astype(np.float32)


def vignette(strength=0.55):
    y, x = np.mgrid[0:H, 0:W]
    d = np.sqrt(((x - W / 2) / (W / 2)) ** 2 + ((y - H / 2) / (H / 2)) ** 2)
    return (1 - strength * np.clip(d - 0.35, 0, None) ** 1.5)[..., None].astype(np.float32)


def blob(radius, blur):
    size = int(radius * 2 + blur * 6) | 1
    img = Image.new("L", (size, size), 0)
    c = size // 2
    ImageDraw.Draw(img).ellipse([c - radius, c - radius, c + radius, c + radius], fill=255)
    img = img.filter(ImageFilter.GaussianBlur(blur))
    return np.asarray(img, dtype=np.float32) / 255.0


def add_sprite(frame, sprite, cx, cy, color, alpha):
    h, w = sprite.shape
    x0, y0 = int(cx - w / 2), int(cy - h / 2)
    xs, ys = max(0, x0), max(0, y0)
    xe, ye = min(W, x0 + w), min(H, y0 + h)
    if xs >= xe or ys >= ye:
        return
    s = sprite[ys - y0 : ye - y0, xs - x0 : xe - x0][..., None]
    frame[ys:ye, xs:xe] += s * np.array(color, dtype=np.float32) * alpha


def periodic(t, T, rng, n=3, amp=1.0):
    """Glatte Schwankung, die nach T Sekunden exakt wieder am Anfang ist."""
    v = 0.0
    for k in range(1, n + 1):
        v += np.sin(2 * np.pi * k * t / T + rng.uniform(0, 2 * np.pi)) * rng.uniform(0.3, 1) / k
    return v * amp


class Periodic:
    """Wie periodic(), aber mit festen Phasen (für Frame-zu-Frame-Konsistenz)."""
    def __init__(self, rng, T, n=3, amp=1.0, kmin=1):
        self.k = np.arange(kmin, kmin + n)
        self.ph = rng.uniform(0, 2 * np.pi, n)
        self.a = rng.uniform(0.3, 1, n) / self.k * amp
        self.T = T

    def __call__(self, t):
        return float(np.sum(self.a * np.sin(2 * np.pi * self.k * t / self.T + self.ph)))


# ----------------------------------------------------------------- Szenen
def scene_regen(rng, T):
    palettes = [
        ((8, 14, 30), (20, 30, 50), [(255, 190, 110), (255, 140, 80), (120, 170, 255)]),
        ((5, 18, 22), (18, 40, 44), [(255, 210, 140), (120, 255, 220), (255, 120, 120)]),
        ((14, 10, 26), (40, 26, 52), [(255, 160, 200), (180, 140, 255), (255, 200, 120)]),
        ((10, 12, 14), (30, 34, 40), [(255, 220, 160), (255, 170, 90), (200, 220, 255)]),
    ]
    top, bot, cols = palettes[rng.integers(len(palettes))]
    bg = gradient(top, bot)
    vig = vignette()
    bokeh = []
    for _ in range(rng.integers(18, 34)):
        r = rng.uniform(8, 40)
        bokeh.append(dict(sprite=blob(r, r * 0.6), x=rng.uniform(0, W), y=rng.uniform(H * 0.2, H * 0.95),
                          col=cols[rng.integers(len(cols))], a=rng.uniform(0.15, 0.55),
                          pulse=Periodic(rng, T, 2, 0.3)))
    drops = []
    for _ in range(rng.integers(260, 420)):
        laps = rng.integers(4, 10)                     # ganze Bildschirmdurchläufe pro Loop
        drops.append((rng.uniform(0, W), rng.uniform(0, H + 80), laps * (H + 80) / T,
                      rng.uniform(10, 34), rng.uniform(25, 80)))
    slant = rng.uniform(-0.12, 0.12)
    # Tropfen auf der Scheibe (statisch, leicht glänzend)
    glass = np.zeros((H, W), np.float32)
    for _ in range(rng.integers(120, 220)):
        r = rng.uniform(1.5, 5)
        s = blob(r, 1.2)
        x, y = int(rng.uniform(0, W)), int(rng.uniform(0, H))
        h, w = s.shape
        ys, xs = slice(max(0, y), min(H, y + h)), slice(max(0, x), min(W, x + w))
        glass[ys, xs] += s[: ys.stop - ys.start, : xs.stop - xs.start]

    def frame(t):
        f = bg.copy()
        for b in bokeh:
            add_sprite(f, b["sprite"], b["x"], b["y"], b["col"], b["a"] * (1 + b["pulse"](t)))
        f += glass[..., None] * 18
        img = Image.fromarray(np.clip(f, 0, 255).astype(np.uint8)).convert("RGBA")
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        for x, y0, v, length, a in drops:
            y = (y0 + v * t) % (H + 80) - 40
            d.line([(x + slant * y, y), (x + slant * (y + length), y + length)],
                   fill=(210, 225, 240, int(a)), width=1)
        img = Image.alpha_composite(img, layer).convert("RGB")
        return np.asarray(img, np.float32) * vig

    return frame


def scene_kamin(rng, T):
    wall = [(22, 12, 8), (30, 18, 12), (16, 14, 18)][rng.integers(3)]
    bg = gradient(tuple(c * 0.6 for c in wall), wall)
    vig = vignette(0.7)
    cx, base = W / 2 + rng.uniform(-40, 40), H * rng.uniform(0.72, 0.78)
    fw = rng.uniform(300, 380)
    # Kaminöffnung (dunkel) + Steinrahmen
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    opening = ((np.abs(x - cx) < fw / 2 + 20) & (y > base - 240) & (y < base + 30)).astype(np.float32)
    opening = ndimage.gaussian_filter(opening, 6)
    frame_mask = ((np.abs(x - cx) < fw / 2 + 70) & (y > base - 300) & (y < base + 60)).astype(np.float32)
    frame_mask = ndimage.gaussian_filter(frame_mask, 3) - opening
    stone = ndimage.gaussian_filter(rng.standard_normal((H, W)).astype(np.float32), 2) * 8
    brick_h = rng.uniform(16, 24)
    row = np.floor(y / brick_h)
    mortar = ((y % brick_h) < 2) | (((x + (row % 2) * 22) % 44) < 2)
    stone -= ndimage.gaussian_filter(mortar.astype(np.float32), 0.8) * 22
    stone_col = np.array([[58, 38, 30], [48, 44, 42], [62, 46, 34]][rng.integers(3)], np.float32)
    # Flammenzungen
    tongues = []
    for _ in range(rng.integers(12, 20)):
        tongues.append(dict(x=cx + rng.normal(0, fw * 0.18), w=rng.uniform(16, 36),
                            h=rng.uniform(70, 170), hmod=Periodic(rng, T, 4, 0.35, kmin=3),
                            sway=Periodic(rng, T, 3, 14, kmin=2)))
    flick = Periodic(rng, T, 5, 0.12, kmin=4)
    embers = [(cx + rng.uniform(-fw * 0.35, fw * 0.35), rng.uniform(0, 1), rng.integers(2, 6),
               rng.uniform(100, 230), rng.uniform(0, 2 * np.pi)) for _ in range(40)]
    ember_s = blob(1.5, 1.0)
    logs = Image.new("L", (W, H), 0)
    ld = ImageDraw.Draw(logs)
    for i in range(3):
        lx = cx + (i - 1) * fw * 0.25
        ld.ellipse([lx - fw * 0.22, base - 18, lx + fw * 0.22, base + 14], fill=255)
    logs = np.asarray(logs.filter(ImageFilter.GaussianBlur(2)), np.float32)[..., None] / 255
    ys = np.arange(H, dtype=np.float32)[:, None]
    xs = np.arange(W, dtype=np.float32)[None, :]

    def colormap(v):
        v = np.clip(v, 0, 1.6)
        r = np.clip(v * 1.6, 0, 1) * 255
        g = np.clip((v - 0.25) * 1.5, 0, 1) * 220
        b = np.clip((v - 0.8) * 1.5, 0, 1) * 180
        return np.stack([r, g, b], -1)

    def frame(t):
        inten = np.zeros((H, W), np.float32)
        for tg in tongues:
            h = tg["h"] * (1 + tg["hmod"](t))
            rel = np.clip((base - ys) / h, 0, None)
            xc = tg["x"] + tg["sway"](t) * rel ** 2
            prof = np.exp(-rel ** 2.2) * (ys < base + 5)
            inten += np.exp(-((xs - xc) / (tg["w"] * (1 - 0.5 * np.clip(rel, 0, 1)))) ** 2) * prof * 0.55
        glow = 1 + flick(t)
        inten += np.exp(-(((xs - cx) / (fw * 0.38)) ** 2 + ((ys - base + 8) / 14) ** 2)) * 0.55 * glow
        room = bg * (0.7 + 0.35 * glow) + frame_mask[..., None] * (stone_col + stone[..., None]) * glow
        room *= (1 - opening[..., None] * 0.85)
        light = np.exp(-(((xs - cx) / 380) ** 2 + ((ys - base) / 260) ** 2)) * 60 * glow
        f = room + light[..., None] * np.array([1.0, 0.55, 0.25])
        f = f * (1 - logs) + logs * np.array([30, 16, 8]) + logs * colormap(inten * 0.5) * 0.5
        flame = colormap(ndimage.gaussian_filter(inten, 1.2))
        f = np.maximum(f, flame * np.clip(inten, 0, 1)[..., None] + f * (1 - np.clip(inten, 0, 1)[..., None]))
        for ex, ph, laps, rise, wob in embers:
            p = (ph + laps * t / T) % 1.0
            add_sprite(f, ember_s, ex + 8 * np.sin(2 * np.pi * 3 * t / T + wob), base - 30 - p * rise,
                       (255, 150, 60), (1 - p) * 1.2)
        return f * vig

    return frame


def scene_wasserfall(rng, T):
    palettes = [
        ((40, 70, 60), (12, 30, 24), (200, 230, 235)),
        ((60, 80, 100), (18, 30, 40), (215, 235, 255)),
        ((90, 100, 80), (25, 35, 25), (230, 240, 230)),
    ]
    top, bot, water = palettes[rng.integers(len(palettes))]
    bg = gradient(top, bot)
    # Bäume / Vegetation im Hintergrund
    veg = ndimage.gaussian_filter(rng.standard_normal((H, W)).astype(np.float32), 6)
    bg *= (0.8 + 0.6 * veg[..., None])
    cx = W / 2 + rng.uniform(-80, 80)
    w_top, w_bot = rng.uniform(120, 200), rng.uniform(200, 320)
    top_y, pool_y = H * rng.uniform(0.08, 0.2), H * rng.uniform(0.74, 0.82)
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    half = w_top / 2 + (w_bot - w_top) / 2 * np.clip((y - top_y) / (pool_y - top_y), 0, 1)
    band = ((np.abs(x - cx) < half) & (y > top_y) & (y < pool_y + 10)).astype(np.float32)
    band = ndimage.gaussian_filter(band, 4)
    # Felsen links/rechts
    jag_l = ndimage.gaussian_filter1d(rng.standard_normal(H) * 40, 6)[:, None]
    jag_r = ndimage.gaussian_filter1d(rng.standard_normal(H) * 40, 6)[:, None]
    # Felskante oben: steigt zu den Rändern hin an, damit Wald/Himmel sichtbar bleibt
    cliff_top = top_y - 10 - np.abs(x - cx) * rng.uniform(0.25, 0.6) \
        + ndimage.gaussian_filter1d(rng.standard_normal(W) * 25, 8)[None, :]
    rocks = (((x < cx - half - 6 + jag_l) | (x > cx + half + 6 + jag_r)) & (y > cliff_top) & (y < pool_y + 4)).astype(np.float32)
    rocks = ndimage.gaussian_filter(rocks, 1.5)
    big = ndimage.gaussian_filter(rng.standard_normal((H, W)).astype(np.float32), 14)
    small = ndimage.gaussian_filter(rng.standard_normal((H, W)).astype(np.float32), 2)
    shade = np.clip(0.55 + big * 4 + small * 0.12, 0.2, 1.2)
    shade *= 0.6 + 0.6 * np.clip(1 - (y - cliff_top) / H, 0, 1)        # oben heller
    moss = np.clip(big * 8, 0, 1)[..., None] * np.array([-10, 25, -5])
    rock_tex = (shade[..., None] * np.array([70, 72, 66]) + moss).astype(np.float32)
    # Laub-Silhouetten auf der Felskante
    leaves = np.zeros((H, W), np.float32)
    for _ in range(60):
        lx = rng.uniform(0, W)
        if abs(lx - cx) < w_top * 0.7:
            continue
        ly = float(cliff_top[0, int(lx)]) + rng.uniform(-10, 15)
        r = rng.uniform(12, 40)
        yy, xx = slice(max(0, int(ly - r)), min(H, int(ly + r))), slice(max(0, int(lx - r)), min(W, int(lx + r)))
        d = ((x[yy, xx] - lx) ** 2 + (y[yy, xx] - ly) ** 2) / r ** 2
        leaves[yy, xx] = np.maximum(leaves[yy, xx], (d < 1).astype(np.float32))
    leaves = ndimage.gaussian_filter(leaves, 2)
    leaf_col = np.array(bot, np.float32) * 0.9 + np.array([0, 18, 6])
    # Wasser-Textur: vertikale Streifen, nahtlos kachelbar
    TH = H * 2
    tex = rng.random((TH, W)).astype(np.float32)
    tex = ndimage.gaussian_filter(tex, (28, 1.6), mode="wrap")
    tex = (tex - tex.min()) / (tex.max() - tex.min())
    speed_laps = rng.integers(3, 6)
    mist = ndimage.gaussian_filter(rng.random((H // 2, W * 2)).astype(np.float32), 18, mode="wrap")
    mist = (mist - mist.min()) / (mist.max() - mist.min())
    mist_mask = np.exp(-((y - pool_y) / 45) ** 2)
    pool = (y > pool_y).astype(np.float32)
    mirror_idx = np.clip((2 * pool_y - np.arange(H)).astype(int), 0, H - 1)
    vig = vignette(0.5)
    water_c = np.array(water, np.float32)

    def frame(t):
        off = int(speed_laps * TH * t / T) % TH
        stream = np.roll(tex, off, axis=0)[:H]
        f = bg.copy()
        wv = (0.55 + 0.6 * stream)[..., None] * water_c
        f = f * (1 - band[..., None]) + wv * band[..., None]
        f = f * (1 - rocks[..., None]) + rock_tex * rocks[..., None]
        f = f * (1 - leaves[..., None]) + leaf_col * leaves[..., None]
        moff = int(W * 2 * t / T) % (W * 2)
        m = np.roll(mist, moff, axis=1)[:, :W]
        m = np.repeat(m, 2, axis=0)[:H]
        f += (m * mist_mask * 140)[..., None] * (water_c / 255)
        refl = f[mirror_idx]  # Spiegelung an der Wasserlinie
        f = f * (1 - pool[..., None]) + pool[..., None] * (refl * 0.35 + np.array(bot) * 0.6)
        return f * vig

    return frame


SCENES = {"regen": scene_regen, "kamin": scene_kamin, "wasserfall": scene_wasserfall}


def render(chan, variant, seconds, out):
    rng = np.random.default_rng(sum(map(ord, chan)) * 100 + variant)
    T = float(seconds)
    make = SCENES[chan](rng, T)
    n = int(T * FPS)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-vf", "scale=1920:1080:flags=lanczos",
           "-c:v", "libx264", "-preset", "slow", "-crf", "22", "-pix_fmt", "yuv420p",
           "-g", str(FPS * 2), "-movflags", "+faststart", "-f", "mp4", str(out) + ".part"]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(n):
        p.stdin.write(np.clip(make(i / FPS), 0, 255).astype(np.uint8).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise SystemExit(f"ffmpeg-Fehler bei {out}")
    Path(str(out) + ".part").replace(out)  # erst fertige Dateien landen im Cache


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variants", type=int, default=3)
    ap.add_argument("--seconds", type=int, default=12, help="Loop-Länge")
    ap.add_argument("--channels", nargs="*", default=list(SCENES))
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    for chan in args.channels:
        out_dir = ASSETS / chan / "video"
        out_dir.mkdir(parents=True, exist_ok=True)
        for v in range(1, args.variants + 1):
            out = out_dir / f"gen_{v:02d}.mp4"
            if out.exists() and not args.force:
                continue
            render(chan, v, args.seconds, out)
            print(f"  ✓ {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
