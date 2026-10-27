#!/usr/bin/env python3
"""
Abwechslungsreiche Vorschau-/Titelbilder – jedes Video bekommt ein eigenes, passendes Bild (kostenlos):

  * Calm Haven: echte Fotos (Pexels/Pixabay) passend zur Szene ("Rain on Window", "Cabin Fireplace" …)
  * Mondmelodie / Gute-Nacht-Kiste: Illustrationen (Pixabay) passend zum Thema/zur Geschichte
  * bereits verwendete Bilder werden gemerkt (data/covers_used.json) -> keine Wiederholungen

  bg = covers.background("regen", "Rain on Window", "landscape", work)     # Pfad oder None
  ig = covers.ig_cover("schlaf", "Gute Nacht, kleiner Stern", "Schlaf gut 🌙", work / "cover.jpg")
"""
import json
import os
import random
import re
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
USED = ROOT / "data" / "covers_used.json"
FONTS = ROOT / "assets" / "fonts"

# Kanal -> (Bildart, Grundbegriffe, Zusatz je Szene-Stichwort)
CHANNEL = {
    "regen": ("photo", "rain", {"window": "rain window night", "forest": "rain forest", "city": "rainy night window",
                                "tent": "tent rain", "porch": "rain porch cozy", "lake": "rain lake", "roof": "rain roof",
                                "thunder": "storm clouds rain", "cabin": "rain cabin"}),
    "kamin": ("photo", "fireplace", {"cabin": "cabin fireplace cozy", "autumn": "autumn fireplace cozy",
                                     "winter": "winter fireplace snow", "country": "country house fireplace",
                                     "campfire": "campfire night", "lake": "campfire lake", "library": "library fireplace",
                                     "rain": "fireplace rain window"}),
    "wasserfall": ("photo", "waterfall", {"forest": "forest waterfall", "mountain": "mountain waterfall",
                                          "stream": "forest stream", "river": "river forest", "rainforest": "rainforest waterfall",
                                          "birds": "forest stream morning", "lake": "lake waterfall"}),
    "schlaf": ("illustration", "moon night sky", {"stern": "stars night sky cute", "wolke": "clouds moon night",
                                                  "mond": "moon night cute", "meer": "sea night moon",
                                                  "wald": "forest night moon", "schaf": "sheep moon night"}),
    "geschichten": ("illustration", "bedtime story night", {}),
    "gedanken": ("photo", "calm nature landscape", {"see": "calm lake morning", "lake": "calm lake morning",
                                                    "wald": "forest light morning", "forest": "forest light",
                                                    "meer": "calm sea sunset", "sea": "calm sea", "berg": "mountains mist",
                                                    "mountain": "mountains mist", "wiese": "meadow sunrise",
                                                    "regen": "rain leaves calm", "schnee": "snow landscape calm"}),
}
STYLE = {   # Schrift/Farbe für Instagram-Titelbilder
    "regen": ("PlayfairDisplay.ttf", (245, 242, 235)), "kamin": ("PlayfairDisplay.ttf", (255, 236, 205)),
    "wasserfall": ("PlayfairDisplay.ttf", (235, 248, 245)), "schlaf": ("Pacifico.ttf", (255, 246, 214)),
    "geschichten": ("Baloo2.ttf", (255, 246, 214)), "gedanken": ("PlayfairDisplay.ttf", (250, 246, 236)),
}
BAD = re.compile(r"\b(car|cars|traffic|street|road|people|person|woman|man|girl|boy|child|face|text|logo|"
                 r"halloween|horror|scary|skull|blood)\b", re.I)


def _used():
    try:
        return set(json.loads(USED.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        return set()


def _mark(pid):
    u = _used()
    u.add(pid)
    USED.parent.mkdir(parents=True, exist_ok=True)
    USED.write_text(json.dumps(sorted(u)[-5000:], indent=0), encoding="utf-8")


def query_for(channel, scene):
    kind, base, extra = CHANNEL[channel]
    s = (scene or "").lower()
    for k, q in extra.items():
        if k in s:
            return kind, q
    if channel == "geschichten" and scene:                  # Geschichte: Stichworte per Gemini (englisch)
        try:
            import sys
            sys.path.insert(0, str(ROOT / "anime"))
            import gemini
            js = gemini.ask_json(f"Give a 2–4 word English image search query for a cute children's book illustration "
                                 f"fitting this bedtime story title: '{scene}'. Only animals/objects/nature, no people. "
                                 'Answer JSON: {"q":"..."}', temperature=0.3)
            return kind, f"{js['q']} illustration"
        except Exception:  # noqa: BLE001
            pass
    return kind, base


def _pexels(q, orientation):
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return []
    r = requests.get("https://api.pexels.com/v1/search", headers={"Authorization": key}, timeout=30,
                     params={"query": q, "orientation": orientation, "per_page": 40, "size": "large"})
    r.raise_for_status()
    return [(f"pexels_{p['id']}", p["src"]["original"], p.get("alt", "")) for p in r.json().get("photos", [])]


def _pixabay(q, orientation, kind):
    key = os.environ.get("PIXABAY_API_KEY")
    if not key:
        return []
    r = requests.get("https://pixabay.com/api/", timeout=30, params={
        "key": key, "q": q, "image_type": "illustration" if kind == "illustration" else "photo",
        "orientation": "horizontal" if orientation == "landscape" else "vertical", "safesearch": "true",
        "per_page": 60, "order": "popular", "min_width": 1280})
    r.raise_for_status()
    return [(f"pixabay_{h['id']}", h.get("largeImageURL"), h.get("tags", "")) for h in r.json().get("hits", [])]


def background(channel, scene, orientation, work: Path, rnd=random):
    """Lädt ein noch nicht verwendetes, passendes Bild. orientation: landscape | portrait. Pfad oder None."""
    kind, q = query_for(channel, scene)
    used = _used()
    cands = []
    try:
        cands = (_pexels(q, orientation) if kind == "photo" else []) + _pixabay(q, orientation, kind)
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ Bildsuche „{q}“: {e}")
    cands = [c for c in cands if c[1] and c[0] not in used and not BAD.search(c[2] or "")]
    if not cands:
        return None
    pick = rnd.choice(cands[: max(5, len(cands) // 2)])          # aus der besseren Hälfte, aber zufällig
    work.mkdir(parents=True, exist_ok=True)
    dst = work / f"cover_bg_{orientation}.jpg"
    try:
        dst.write_bytes(requests.get(pick[1], timeout=60).content)
        Image.open(dst).verify()
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ Bild laden: {e}")
        return None
    _mark(pick[0])
    print(f"  🖼 Titelbild: {pick[0]} („{q}“)")
    return dst


def fit(img_path, w, h):
    im = Image.open(img_path).convert("RGB")
    s = max(w / im.width, h / im.height)
    im = im.resize((int(im.width * s + 1), int(im.height * s + 1)), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def _font(name, size):
    try:
        f = ImageFont.truetype(str(FONTS / name), size)
        try:
            f.set_variation_by_name("Bold")
        except Exception:  # noqa: BLE001
            pass
        return f
    except Exception:  # noqa: BLE001
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)


def ig_cover(channel, title, sub, out: Path, work=None, rnd=random):
    """Instagram-Titelbild 1080x1920: passendes Bild + Titel (lesbar im Profil-Raster, Mitte 1080x1350)."""
    bg = background(channel, title if channel == "geschichten" else sub or title, "portrait", Path(work or out.parent), rnd)
    if not bg:
        return None
    im = ImageEnhance.Brightness(fit(bg, 1080, 1920)).enhance(0.8)
    shade = Image.new("L", (1080, 1920), 0)
    d = ImageDraw.Draw(shade)
    for y in range(1920):
        d.line([(0, y), (1080, y)], fill=int(150 * max(0, 1 - abs(y - 960) / 520)))
    im = Image.composite(Image.new("RGB", im.size, (0, 0, 0)), im, shade)
    d = ImageDraw.Draw(im)
    fname, color = STYLE.get(channel, ("PlayfairDisplay.ttf", (255, 255, 255)))
    title = re.sub(r"#\w+", "", title).strip()
    size = 112
    while size > 56:
        f = _font(fname, size)
        words, lines, cur = title.split(), [], ""
        for w_ in words:
            t = (cur + " " + w_).strip()
            if d.textlength(t, font=f) > 900 and cur:
                lines.append(cur)
                cur = w_
            else:
                cur = t
        lines.append(cur)
        if len(lines) <= 3:
            break
        size -= 8
    y = 960 - len(lines) * size * 0.62
    for ln in lines:
        d.text((540, y), ln, font=f, fill=color, anchor="mm", stroke_width=3, stroke_fill=(0, 0, 0))
        y += size * 1.2
    im.save(out, quality=92)
    return out


_ = ImageFilter
