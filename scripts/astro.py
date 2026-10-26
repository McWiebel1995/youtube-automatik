#!/usr/bin/env python3
"""
Astro-Karussells für Instagram (englisch, Stil: himmlisch & mystisch – Nachtblau, Gold, Sterne).

Jeden Tag ein Karussell (4:5, 1080x1350), Formate im Wechsel:
  signs   – Titelbild + 4 Element-Folien (Feuer/Erde/Luft/Wasser, je 3 Zeichen) + Schlussfolie
  months  – Titelbild + 4 Folien mit je 3 Geburtsmonaten + Schlussfolie
  message – große Überschrift + 4 Textfolien (je 3 Zeichen) + Schlussfolie

Inhalt: Gemini · Bilder: Qwen-Image (Modal) · Satz: Pillow · Posten: Instagram-Karussell (scripts/instagram.py)
Unterhaltung, keine Ratschläge zu Gesundheit/Geld; positive, warme Sprache statt Angstmache.

    python scripts/astro.py --out output/astro [--dry-run] [--format signs|months|message]
"""
import argparse
import datetime as dt
import json
import os
import random
import re
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT / "anime")]

W, H = 1080, 1350
USED = ROOT / "data" / "astro_used.json"
FONTS = ROOT / "assets" / "fonts"
GOLD, GOLD2, INK, NIGHT = (231, 196, 120), (250, 226, 170), (238, 232, 248), (10, 14, 38)
ELEMENTS = [("Fire", ["Aries", "Leo", "Sagittarius"], "♈ ♌ ♐"),
            ("Earth", ["Taurus", "Virgo", "Capricorn"], "♉ ♍ ♑"),
            ("Air", ["Gemini", "Libra", "Aquarius"], "♊ ♎ ♒"),
            ("Water", ["Cancer", "Scorpio", "Pisces"], "♋ ♏ ♓")]
GLYPH = {"Aries": "♈", "Taurus": "♉", "Gemini": "♊", "Cancer": "♋", "Leo": "♌", "Virgo": "♍", "Libra": "♎",
         "Scorpio": "♏", "Sagittarius": "♐", "Capricorn": "♑", "Aquarius": "♒", "Pisces": "♓"}
MONTHS = [["January", "February", "March"], ["April", "May", "June"], ["July", "August", "September"],
          ["October", "November", "December"]]
STYLE = ("ethereal celestial fine-art illustration, deep midnight blue and navy, luminous gold accents, "
         "glowing stars and nebula, crescent moon, soft dreamy light, painterly, elegant, mystical, high detail, "
         "no text, no letters, no watermark")
ELEMENT_SCENES = {
    "Fire": "a radiant figure made of golden starlight holding a small flame under a starry sky",
    "Earth": "a moonlit enchanted forest with golden constellations above ancient trees",
    "Air": "a graceful figure with flowing hair dissolving into stars and drifting feathers, night sky",
    "Water": "a calm ocean reflecting the full moon and a river of stars, a silhouette at the shore",
}

TASK = """You write for a new English Instagram astrology account (style: celestial, warm, poetic, a little mysterious;
never fear-mongering, no medical/financial/legal advice, entertainment only). Today's format: {fmt}.
Avoid these recent themes: {used}

Pick ONE fresh, highly shareable theme (people should save it and send it to a friend), e.g. themes like
"what your sign needs to hear tonight", "the quiet strength of each sign", "your birth month's secret gift",
"how each sign loves when no one is watching", "the moon's message for your sign this week".
Write:
- hook: cover headline, max 7 words, intriguing (Title Case)
- subline: max 6 words, italic-style second line
- entries: {entries_hint} – each 22–34 words, second person ("you"), specific and emotional, no clichés repeated
- cover_scene: a short visual scene for the cover illustration fitting the theme (celestial, no text)
- caption: 2–3 short sentences + a question that invites comments (e.g. "Which one is you? 🌙"), no hashtags
- hashtags: exactly 5 (mix big + niche), e.g. #astrology #zodiacsigns ...
Answer ONLY JSON: {{"theme":"...","hook":"...","subline":"...","cover_scene":"...","entries":{{{keys}}},
"caption":"...","hashtags":["#..."]}}"""


# ----------------------------------------------------------------- Schriften
def font(name, size, weight=None):
    f = FONTS / name
    try:
        ft = ImageFont.truetype(str(f), size)
        if weight:
            try:
                ft.set_variation_by_axes([weight])
            except Exception:  # noqa: BLE001
                pass
        return ft
    except Exception:  # noqa: BLE001
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", size)


def glyph_font(size):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", str(FONTS / "NotoSansSymbols.ttf")):
        try:
            return ImageFont.truetype(p, size)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


TITLE = lambda s: font("Cinzel.ttf", s, 700)          # noqa: E731
SERIF = lambda s: font("CormorantGaramond.ttf", s, 500)  # noqa: E731
SERIF_I = lambda s: font("CormorantGaramond.ttf", s, 400)  # noqa: E731


def wrap(d, text, f, maxw):
    words, lines, cur = text.split(), [], ""
    for w_ in words:
        t = (cur + " " + w_).strip()
        if d.textlength(t, font=f) > maxw and cur:
            lines.append(cur)
            cur = w_
        else:
            cur = t
    return lines + ([cur] if cur else [])


# ----------------------------------------------------------------- Hintergründe
def starfield(seed):
    rnd = random.Random(seed)
    im = Image.new("RGB", (W, H), NIGHT)
    d = ImageDraw.Draw(im)
    for y in range(H):                                 # Verlauf Nachtblau -> Indigo
        k = y / H
        d.line([(0, y), (W, y)], fill=(int(10 + 18 * k), int(14 + 10 * k), int(38 + 34 * k)))
    for _ in range(420):
        x, y, r = rnd.uniform(0, W), rnd.uniform(0, H), rnd.choice([0.6, 0.8, 1, 1, 1.4, 2])
        a = rnd.randint(110, 255)
        d.ellipse([x - r, y - r, x + r, y + r], fill=(a, a, min(255, a + 10)))
    return im.filter(ImageFilter.GaussianBlur(0.4))


def fit_bg(png_bytes, dim=0.55, blur=0):
    import io
    im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    s = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * s + 1), int(im.height * s + 1)), Image.LANCZOS)
    x, y = (im.width - W) // 2, (im.height - H) // 2
    im = im.crop((x, y, x + W, y + H))
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    return ImageEnhance.Brightness(im).enhance(dim)


def veil(im, top=0.0, bottom=0.85):
    """Dunkler Verlauf für lesbaren Text."""
    ov = Image.new("L", (W, H))
    d = ImageDraw.Draw(ov)
    for y in range(H):
        k = y / H
        d.line([(0, y), (W, y)], fill=int(255 * (top + (bottom - top) * k ** 1.6)))
    dark = Image.new("RGB", (W, H), (6, 8, 24))
    return Image.composite(dark, im, ov)


def frame(d, inset=34):
    d.rectangle([inset, inset, W - inset, H - inset], outline=GOLD + (170,), width=2)
    d.rectangle([inset + 9, inset + 9, W - inset - 9, H - inset - 9], outline=GOLD + (70,), width=1)
    for cx, cy in ((W // 2, inset), (W // 2, H - inset)):                       # kleine Sterne im Rahmen
        d.regular_polygon((cx, cy, 9), 4, rotation=45, fill=GOLD)


def handle_line(d, handle):
    f = SERIF_I(30)
    d.text((W // 2, H - 72), f"@{handle}" if handle else "", font=f, fill=GOLD, anchor="mm")


# ----------------------------------------------------------------- Folien
def cover(bg, hook, subline, handle, label):
    im = veil(bg, 0.15, 0.92)
    d = ImageDraw.Draw(im, "RGBA")
    frame(d)
    d.text((W // 2, 112), label.upper(), font=TITLE(30), fill=GOLD, anchor="mm")
    ft = TITLE(92)
    lines = wrap(d, hook.upper(), ft, W - 180)
    while len(lines) > 3:
        ft = TITLE(ft.size - 8)
        lines = wrap(d, hook.upper(), ft, W - 180)
    block = len(lines) * ft.size * 1.12 + 90
    y = H - 240 - block + ft.size * 0.5                 # Block endet über „swipe“
    for ln in lines:
        d.text((W // 2, y), ln, font=ft, fill=GOLD2, anchor="mm", stroke_width=1, stroke_fill=(30, 22, 6))
        y += ft.size * 1.12
    d.text((W // 2, y + 34), subline, font=SERIF_I(54), fill=INK, anchor="mm")
    d.text((W // 2 - 22, H - 140), "swipe", font=SERIF_I(36), fill=GOLD, anchor="mm")
    d.text((W // 2 + 42, H - 138), "→", font=glyph_font(34), fill=GOLD, anchor="mm")
    handle_line(d, handle)
    return im


def group_slide(bg, title, glyphs, items, handle):
    """items: [(name, glyph, text)] – 3 Einträge."""
    im = veil(bg, 0.55, 0.88)
    d = ImageDraw.Draw(im, "RGBA")
    frame(d)
    d.text((W // 2, 120), title.upper(), font=TITLE(52), fill=GOLD2, anchor="mm")
    if glyphs:
        d.text((W // 2, 182), glyphs, font=glyph_font(40), fill=GOLD, anchor="mm")
    y = 250
    fb = SERIF(40)
    for name, gl, text in items:
        d.line([(W // 2 - 60, y), (W // 2 + 60, y)], fill=GOLD + (140,), width=1)
        y += 36
        ftn = TITLE(40)
        d.text((W // 2, y + 14), name.upper(), font=ftn, fill=GOLD2, anchor="mm")
        if gl:                                           # Tierkreiszeichen links neben dem Namen
            tw = d.textlength(name.upper(), font=ftn)
            d.text((W // 2 - tw / 2 - 34, y + 14), gl, font=glyph_font(38), fill=GOLD, anchor="mm")
        y += 74
        for ln in wrap(d, text, fb, W - 210):
            d.text((W // 2, y), ln, font=fb, fill=INK, anchor="mm")
            y += 49
        y += 24
    handle_line(d, handle)
    return im


def message_cover(bg, hook, subline, handle):
    im = veil(bg, 0.35, 0.8)
    d = ImageDraw.Draw(im, "RGBA")
    frame(d)
    ft = TITLE(104)
    lines = wrap(d, hook.upper(), ft, W - 170)
    while len(lines) > 4:
        ft = TITLE(ft.size - 8)
        lines = wrap(d, hook.upper(), ft, W - 170)
    y = H / 2 - (len(lines) * ft.size * 1.1) / 2
    for ln in lines:
        d.text((W // 2, y), ln, font=ft, fill=GOLD2, anchor="mm")
        y += ft.size * 1.1
    d.text((W // 2, y + 40), subline, font=SERIF_I(54), fill=INK, anchor="mm")
    handle_line(d, handle)
    return im


def outro(bg, handle):
    im = veil(bg, 0.6, 0.9)
    d = ImageDraw.Draw(im, "RGBA")
    frame(d)
    d.text((W // 2, H / 2 - 170), "✦", font=glyph_font(80), fill=GOLD, anchor="mm")
    for k, (t, f) in enumerate([("SAVE THIS", TITLE(70)), ("for the nights you need it", SERIF_I(50)),
                                ("", None), ("SEND IT", TITLE(70)), ("to the friend who felt this", SERIF_I(50))]):
        if f:
            d.text((W // 2, H / 2 - 70 + k * 78), t, font=f, fill=GOLD2 if f.size == 70 else INK, anchor="mm")
    d.text((W // 2, H - 150), f"follow @{handle} for daily cosmic notes" if handle else "follow for daily cosmic notes",
           font=SERIF_I(36), fill=GOLD, anchor="mm")
    return im


# ----------------------------------------------------------------- Inhalt
def plan(fmt, rnd):
    import gemini
    used = json.loads(USED.read_text(encoding="utf-8")) if USED.exists() else []
    if fmt == "months":
        keys = ", ".join(f'"{m}":"..."' for g in MONTHS for m in g)
        hint = "one entry per birth month (January … December)"
    else:
        keys = ", ".join(f'"{s}":"..."' for _, g, _ in ELEMENTS for s in g)
        hint = "one entry per zodiac sign (Aries … Pisces)"
    fmt_desc = {"signs": "zodiac signs grouped by element, illustrated", "months": "birth months, illustrated",
                "message": "bold message headline + text slides per sign"}[fmt]
    js = gemini.ask_json(TASK.format(fmt=fmt_desc, used="; ".join(used[-60:]) or "none", entries_hint=hint, keys=keys),
                         temperature=1.0)
    js["format"] = fmt
    return js


# ----------------------------------------------------------------- Ablauf
def build(out: Path, fmt=None, seed=None, handle=""):
    rnd = random.Random(seed)
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    fmt = fmt or ["signs", "months", "message"][dt.date.today().toordinal() % 3]
    js = plan(fmt, rnd)
    print(f"▶ {fmt}: {js['hook']} – {js.get('theme', '')}")
    ent = js["entries"]
    groups = ([(m[0] + " – " + m[-1], "", [(x, "", ent.get(x, "")) for x in m]) for m in MONTHS] if fmt == "months" else
              [(f"{el} signs", gl, [(s, GLYPH[s], ent.get(s, "")) for s in g]) for el, g, gl in ELEMENTS])
    # Bilder (Qwen-Image auf Modal); ohne Modal: Sternenhimmel
    prompts = [f"{js.get('cover_scene', 'a woman gazing at a crescent moon')}, {STYLE}"]
    prompts += ([f"{ELEMENT_SCENES[el]}, {STYLE}" for el, _, _ in ELEMENTS] if fmt != "months" else
                [f"{s}, {STYLE}" for s in ("winter night sky over snowy hills, aurora", "spring blossoms under moonlight",
                                            "summer meadow with fireflies and milky way", "autumn forest under a harvest moon")])
    bgs = []
    try:
        import modal
        from modal_app import ImageFlux, app, download_flux
        with modal.enable_output(), app.run():
            download_flux.remote()
            fl = ImageFlux()
            for k, p in enumerate(prompts):
                bgs.append(fl.generate.remote(p, seed=rnd.randrange(10**6), width=1104, height=1376))
                print(f"  Bild {k + 1}/{len(prompts)}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"::warning title=Bilder::Ohne KI-Bilder (Sternenhimmel): {str(e)[:300]}")
    def bg(k, dim):
        return fit_bg(bgs[k], dim) if k < len(bgs) else starfield(rnd.randrange(10**6))
    slides = []
    if fmt == "message":
        slides.append(message_cover(bg(0, 0.45), js["hook"], js.get("subline", ""), handle))
    else:
        label = "your birth month" if fmt == "months" else "the zodiac signs"
        slides.append(cover(bg(0, 0.85), js["hook"], js.get("subline", ""), handle, label))
    for k, (title, gl, items) in enumerate(groups):
        slides.append(group_slide(bg(k + 1, 0.42) if fmt != "message" else bg(0, 0.25), title, gl, items, handle))
    slides.append(outro(bg(0, 0.35), handle))
    files = []
    for k, im in enumerate(slides):
        p = out / f"slide_{k + 1:02d}.jpg"
        im.save(p, quality=92, subsampling=0)
        files.append(p.name)
    caption = js.get("caption", "").strip()
    tags = " ".join((js.get("hashtags") or ["#astrology", "#zodiacsigns", "#horoscope", "#zodiac", "#astrologymemes"])[:5])
    meta = {"format": fmt, "theme": js.get("theme", ""), "hook": js["hook"], "caption": f"{caption}\n\n{tags}".strip(),
            "slides": files, "entries": ent}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


def publish(out: Path, meta: dict, account="astro"):
    import ig_queue
    import instagram
    urls = [ig_queue.upload_public(out / f, f"astro-{dt.datetime.now():%Y%m%d-%H%M%S}-{f}") for f in meta["slides"]]
    mid, link = instagram.publish_carousel(account, urls, meta["caption"])
    print(f"  ✓ Karussell: {link}")
    used = json.loads(USED.read_text(encoding="utf-8")) if USED.exists() else []
    USED.write_text(json.dumps((used + [meta.get("theme") or meta["hook"]])[-300:], ensure_ascii=False, indent=1),
                    encoding="utf-8")
    import upload
    upload.mark_uploaded("astro")
    return link


AVATARS = [
    "a glowing golden crescent moon centered, cradling a small bright star, tiny constellations around, deep midnight blue",
    "a serene woman's face in profile made of soft starlight, crescent moon in her hair, centered, deep navy and gold",
    "an ornate golden zodiac wheel with a crescent moon in the center, glowing, centered, deep midnight blue night sky",
    "a delicate golden hand holding a tiny glowing moon, stars falling softly, centered composition, deep navy",
]


def avatars(out: Path):
    """Profilbild-Vorschläge (1:1, Motiv mittig – passt in den runden Instagram-Ausschnitt)."""
    import modal
    from modal_app import ImageFlux, app, download_flux
    out.mkdir(parents=True, exist_ok=True)
    with modal.enable_output(), app.run():
        download_flux.remote()
        fl = ImageFlux()
        for k, p in enumerate(AVATARS):
            png = fl.generate.remote(f"{p}, icon-like, simple and bold, generous margin around the subject, {STYLE}",
                                     seed=700 + k, width=1328, height=1328)
            (out / f"profilbild_{k + 1}.png").write_bytes(png)
            print(f"  Profilbild {k + 1}/{len(AVATARS)}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--avatar", action="store_true", help="nur Profilbild-Vorschläge erzeugen")
    ap.add_argument("--out", default="output/astro")
    ap.add_argument("--format", choices=["signs", "months", "message"])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.avatar:
        avatars(Path(a.out))
        sys.exit(0)
    handle = os.environ.get("IG_USER_ASTRO", "")
    if not handle and os.environ.get("IG_TOKEN_LERNBAERCHEN"):    # Benutzername direkt vom Konto holen
        try:
            import instagram
            handle = instagram.me(instagram.token_for("astro")).get("username", "")
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ Benutzername nicht lesbar: {e}")
    if handle == "lernbaerchenig":                          # noch nicht umbenannt -> nicht posten, nur Vorschau
        print("  ⚠ Konto heißt noch @lernbaerchenig – nur Vorschau, bitte zuerst umbenennen.")
        handle, a.dry_run = "", True
    if not a.dry_run:
        import upload
        if os.environ.get("FORCE_UPLOAD") != "1" and upload.uploaded_today("astro"):
            print("Heute schon gepostet – übersprungen.")
            sys.exit(0)
    m = build(Path(a.out), a.format, handle=handle)
    if not a.dry_run:
        publish(Path(a.out), m)
    _ = textwrap
