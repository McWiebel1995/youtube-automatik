#!/usr/bin/env python3
"""Produktbilder für den Tacticn-Shopify-Checkout aus echten Zeichen im Baukasten (tacticn.de)."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
GREEN, TAN, DARK = (60, 73, 45), (203, 190, 140), (20, 26, 16)
S = 2048
ROOT = Path(__file__).resolve().parent.parent
# (Familie, Einheitsebene, Zugehörigkeit)
SYMS = {"inf": ("10-1211", "14", "3"), "pz": ("10-1205", "15", "3"), "aufkl": ("10-1213", "15", "3"),
        "art": ("10-1303", "16", "3"), "fla": ("10-1301", "15", "3"), "inf_feind": ("10-1211", "15", "6")}


def shots(work: Path):
    from playwright.sync_api import sync_playwright
    out = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 432, "height": 768}, device_scale_factor=3, locale="de-DE")
        page = ctx.new_page()
        for key, (fam, ech, ident) in SYMS.items():
            page.goto(f"https://tacticn.de/baukasten/{fam}", wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(800)
            for label, val in (("Zugehörigkeit", ident), ("Einheitsebene", ech)):
                try:
                    page.locator(f'select[aria-label="{label}"]').first.select_option(val, timeout=4000)
                    page.wait_for_timeout(700)
                except Exception as e:  # noqa: BLE001
                    print(key, label, e)
            box = page.evaluate("""() => { let best=null, area=0;
                for (const s of document.querySelectorAll('svg')) { const r=s.getBoundingClientRect(); const a=r.width*r.height;
                  if (r.width>60 && r.height>40 && a>area) { area=a; best=s; } }
                if (!best) return null; best.scrollIntoView({block:'center'}); const r=best.getBoundingClientRect();
                return {x:r.left, y:r.top, width:r.width, height:r.height}; }""")
            page.wait_for_timeout(300)
            f = work / f"{key}.png"
            page.screenshot(path=str(f), clip={"x": box["x"] + 4, "y": box["y"] + 4, "width": box["width"] - 8,
                                               "height": box["height"] - 8})
            out[key] = f
        b.close()
    return out


def font(size, fonts):
    f = ImageFont.truetype(str(Path(fonts) / "Oswald.ttf"), size)
    try:
        f.set_variation_by_axes([700])
    except Exception:  # noqa: BLE001
        pass
    return f


def base(fonts, title, sub):
    im = Image.new("RGB", (S, S), GREEN)
    d = ImageDraw.Draw(im)
    for x in range(0, S, 96):
        d.line([(x, 0), (x, S)], fill=(67, 81, 51), width=3)
        d.line([(0, x), (S, x)], fill=(67, 81, 51), width=3)
    logo = Image.open(ROOT / "assets/brand/tacticn_icon.png").convert("RGBA").resize((210, 210))
    im.paste(logo, (90, 80), logo)
    d.text((330, 125), "TACTICN", font=font(110, fonts), fill=TAN, anchor="lm")
    d.text((334, 222), "by CICCO", font=font(46, fonts), fill=(230, 226, 205), anchor="lm")
    d.text((S // 2, S - 330), title, font=font(150, fonts), fill=(255, 255, 255), anchor="mm")
    d.text((S // 2, S - 170), sub, font=font(70, fonts), fill=TAN, anchor="mm")
    return im, d


def card(im, d, img, x, y, w, hmax=None):
    s = Image.open(img).convert("RGB")
    s = s.resize((w, int(s.height * w / s.width)))
    if hmax and s.height > hmax:                     # hohe Zeichen (Raute) einpassen, mittig auf weißer Karte
        t = s.resize((int(s.width * hmax / s.height), hmax))
        s = Image.new("RGB", (w, hmax), t.getpixel((2, 2)))
        s.paste(t, ((w - t.width) // 2, 0))
    d.rounded_rectangle([x - 24, y - 24, x + s.width + 24, y + s.height + 24], radius=40, fill=DARK)
    im.paste(s, (x, y))
    return s.height


def main(out_dir="out", fonts="fonts"):
    out = Path(out_dir)
    out.mkdir(exist_ok=True)
    work = out / "work"
    work.mkdir(exist_ok=True)
    sh = shots(work)
    for name, title, sub in (("stl", "STL-DRUCKDATEI", "APP-6(D) · 5,2 mm · optional mit Magnettasche"),
                             ("gedruckt", "GEDRUCKTES SYMBOL", "Fertig gedruckt · mit Magnettasche Ø 10,1 mm")):
        im, d = base(fonts, title, sub)
        w = 1400
        h = Image.open(sh["inf"]).height * w // Image.open(sh["inf"]).width
        card(im, d, sh["inf"], (S - w) // 2, 420 + (1150 - h) // 2, w)
        im.save(out / f"tacticn_produkt_{name}.jpg", quality=92)
    im, d = base(fonts, "SYMBOL-SET", "Komplettes Paket · STL-Download")
    keys = ["inf", "pz", "aufkl", "art", "fla", "inf_feind"]
    w, gap = 560, 70
    x0 = (S - (3 * w + 2 * gap)) // 2
    for i, k in enumerate(keys):
        card(im, d, sh[k], x0 + (i % 3) * (w + gap), 450 + (i // 3) * 560, w, hmax=470)
    im.save(out / "tacticn_produkt_set.jpg", quality=92)
    print("::notice title=Produktbilder::3 Bilder erstellt")


if __name__ == "__main__":
    main(*sys.argv[1:])
