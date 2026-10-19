"""
Ruhige, nahtlos loopende Kinder-Szenen (komplett selbst gezeichnet):
  nachthimmel(rng, T) -> Sterne funkeln, Mond leuchtet, Wolken ziehen, Hügel
  bilderbuch(rng, T)  -> wie oben + kleines Haus mit Licht, Bäume, Glühwürmchen
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

W, H = 960, 540

PALETTES = [
    dict(top=(10, 14, 48), bot=(46, 40, 100), hill1=(22, 30, 70), hill2=(14, 20, 50), cloud=(90, 90, 150)),
    dict(top=(18, 10, 44), bot=(80, 46, 110), hill1=(36, 22, 70), hill2=(22, 14, 48), cloud=(120, 90, 150)),
    dict(top=(6, 22, 40), bot=(30, 70, 100), hill1=(14, 44, 60), hill2=(8, 30, 42), cloud=(80, 120, 150)),
    dict(top=(12, 12, 30), bot=(40, 50, 90), hill1=(24, 40, 54), hill2=(16, 26, 40), cloud=(100, 110, 140)),
]


def _grad(top, bot, w=W, h=H):
    t = np.linspace(0, 1, h)[:, None, None]
    g = np.array(top)[None, None] * (1 - t) + np.array(bot)[None, None] * t
    return np.repeat(g, w, axis=1).astype(np.float32)


def _glow(radius, blur, w=W, h=H, cx=0, cy=0):
    img = Image.new("L", (w, h), 0)
    ImageDraw.Draw(img).ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=255)
    return np.asarray(img.filter(ImageFilter.GaussianBlur(blur)), np.float32) / 255


def _hill(rng, base_y, amp, w=W, h=H):
    x = np.arange(w)
    y = base_y + sum(amp / k * np.sin(2 * np.pi * k * x / w * rng.uniform(0.6, 1.4) + rng.uniform(0, 6))
                     for k in (1, 2, 3))
    mask = (np.arange(h)[:, None] > y[None, :]).astype(np.float32)
    return np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.2)),
                      np.float32)[..., None] / 255, y


def _cloud_sprite(rng, cw, ch, pad=28):
    img = Image.new("L", (cw + 2 * pad, ch + 2 * pad), 0)
    d = ImageDraw.Draw(img)
    for _ in range(7):
        r = rng.uniform(ch * 0.25, ch * 0.45)
        cx, cy = pad + rng.uniform(r, cw - r), pad + rng.uniform(ch * 0.45, ch * 0.7)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    return np.asarray(img.filter(ImageFilter.GaussianBlur(8)), np.float32) / 255


def nachthimmel(rng, T, house=False):
    pal = PALETTES[rng.integers(len(PALETTES))]
    sky = _grad(pal["top"], pal["bot"])
    # Sterne
    n = rng.integers(140, 220)
    sx, sy = rng.uniform(0, W, n), rng.uniform(0, H * 0.7, n)
    size = rng.choice([1, 1, 1, 2, 2, 3], n)
    speed = rng.integers(1, 4, n)
    phase = rng.uniform(0, 2 * np.pi, n)
    # Mond
    mx, my, mr = rng.uniform(W * 0.15, W * 0.85), rng.uniform(H * 0.12, H * 0.3), rng.uniform(32, 48)
    moon = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(moon)
    md.ellipse([mx - mr, my - mr, mx + mr, my + mr], fill=255)
    if rng.random() < 0.6:  # Sichel
        off = mr * rng.uniform(0.45, 0.65)
        md.ellipse([mx - mr + off, my - mr - off * 0.3, mx + mr + off, my + mr - off * 0.3], fill=0)
    moon = np.asarray(moon.filter(ImageFilter.GaussianBlur(1)), np.float32)[..., None] / 255
    halo = _glow(mr * 1.6, mr * 1.4, cx=mx, cy=my)[..., None]
    # Hügel
    h1, y1 = _hill(rng, H * 0.72, 30)
    h2, y2 = _hill(rng, H * 0.82, 22)
    # Wolken (wandern einmal pro Loop über eine doppelte Bildbreite)
    clouds = []
    for _ in range(rng.integers(3, 6)):
        cw, ch = int(rng.uniform(160, 300)), int(rng.uniform(60, 100))
        clouds.append((_cloud_sprite(rng, cw, ch), rng.uniform(0, 2 * W), rng.uniform(H * 0.08, H * 0.45),
                       rng.uniform(0.25, 0.5), int(rng.choice([1, -1]))))
    # Haus + Bäume für die Bilderbuch-Szene
    extra = None
    flies = []
    if house:
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        hx = rng.uniform(W * 0.2, W * 0.75)
        gy = float(y1[int(hx)]) + 6
        dark = tuple(int(c * 0.6) for c in pal["hill1"])
        d.rectangle([hx - 40, gy - 60, hx + 40, gy], fill=dark + (255,))
        d.polygon([(hx - 52, gy - 58), (hx, gy - 105), (hx + 52, gy - 58)], fill=dark + (255,))
        d.rectangle([hx + 18, gy - 100, hx + 30, gy - 78], fill=dark + (255,))
        win = (255, 205, 120, 255)
        d.rectangle([hx - 26, gy - 44, hx - 8, gy - 26], fill=win)
        d.rectangle([hx + 8, gy - 44, hx + 26, gy - 26], fill=win)
        for _ in range(rng.integers(3, 6)):
            tx = rng.uniform(30, W - 30)
            if abs(tx - hx) < 90:
                continue
            ty = float(y1[int(tx)]) + 4
            th = rng.uniform(50, 110)
            d.rectangle([tx - 4, ty - th * 0.35, tx + 4, ty], fill=dark + (255,))
            d.ellipse([tx - th * 0.32, ty - th, tx + th * 0.32, ty - th * 0.25], fill=dark + (255,))
        extra = np.asarray(layer, np.float32) / 255
        window_glow = _glow(30, 22, cx=hx, cy=gy - 35)[..., None] * np.array([255, 190, 110]) * 0.5
        for _ in range(18):
            flies.append((rng.uniform(0, W), rng.uniform(H * 0.6, H * 0.9), rng.uniform(10, 40),
                          int(rng.integers(1, 3)), rng.uniform(0, 6.28)))

    def frame(t):
        f = sky.copy()
        tw = 0.55 + 0.45 * np.sin(2 * np.pi * speed * t / T + phase)
        img = Image.fromarray(np.clip(f, 0, 255).astype(np.uint8))
        d = ImageDraw.Draw(img)
        for x, y, s, b in zip(sx, sy, size, tw):
            c = int(150 + 105 * b)
            d.ellipse([x - s / 2, y - s / 2, x + s / 2, y + s / 2], fill=(c, c, min(255, c + 10)))
        f = np.asarray(img, np.float32)
        breathe = 0.9 + 0.1 * np.sin(2 * np.pi * t / T)
        f += halo * np.array([255, 240, 200]) * 0.35 * breathe
        f = f * (1 - moon) + moon * np.array([255, 246, 210])
        for spr, x0, cy, alpha, direction in clouds:
            x = (x0 + direction * 2 * W * t / T) % (2 * W) - W / 2
            ch_, cw_ = spr.shape
            xs, xe = int(max(0, x)), int(min(W, x + cw_))
            ys, ye = int(cy), int(min(H, cy + ch_))
            if xs < xe and ys < ye:
                s = spr[: ye - ys, xs - int(x): xe - int(x)][..., None] * alpha
                f[ys:ye, xs:xe] = f[ys:ye, xs:xe] * (1 - s) + s * np.array(pal["cloud"])
        f = f * (1 - h1) + h1 * np.array(pal["hill1"])
        if extra is not None:
            a = extra[..., 3:4]
            f = f * (1 - a) + extra[..., :3] * 255 * a + window_glow * breathe
        f = f * (1 - h2) + h2 * np.array(pal["hill2"])
        if flies:
            img = Image.fromarray(np.clip(f, 0, 255).astype(np.uint8))
            d = ImageDraw.Draw(img)
            for x, y, r, k, ph in flies:
                px = x + r * np.sin(2 * np.pi * k * t / T + ph)
                py = y + r * 0.5 * np.cos(2 * np.pi * k * t / T + ph)
                b = 0.5 + 0.5 * np.sin(2 * np.pi * (k + 2) * t / T + ph)
                d.ellipse([px - 2, py - 2, px + 2, py + 2], fill=(int(200 + 55 * b), int(220 + 35 * b), 120))
            f = np.asarray(img.filter(ImageFilter.GaussianBlur(0.4)), np.float32)
        return f

    return frame


def bilderbuch(rng, T):
    return nachthimmel(rng, T, house=True)
