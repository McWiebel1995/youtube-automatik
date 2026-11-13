#!/usr/bin/env python3
"""
Tacticn – Reihe „Zeichen erklärt“: scharfe Aufnahmen vom echten Tacticn-Baukasten (tacticn.de) + Erklärtexte + Musik.

  python scripts/tacticn_reel.py --episode infanteriezug --out out/

Ablauf: Playwright öffnet den Baukasten im Handyformat, stellt die Auswahl um (Zugehörigkeit, Einheitsebene) und
nimmt das Zeichen jeweils hochauflösend auf. Daraus werden 1080x1920-Bilder (Tacticn-Grün, Zeichen groß, Text),
die mit sanftem Zoom und Überblendungen zum Reel werden. Keine Stimme (Text + CC0-Musik). Fakten nach APP-6(D).
"""
import argparse
import os
import subprocess
from pathlib import Path

import requests

W, H = 1080, 1920
GREEN, TAN = (60, 73, 45), (203, 190, 140)
SEG = 3.0             # Sekunden pro Bild
XF = 0.35             # Überblendung

EPISODES = {
    "infanteriezug": {
        "no": 1,
        "url": "https://tacticn.de/baukasten/10-1211",
        "title": "Infanteriezug",
        "setup": [("Zugehörigkeit", "3"), ("Einheitsebene", "14")],
        "hook": "Weißt du, was dieses\nZeichen bedeutet?",
        "steps": [("friend", "Blaues Rechteck\n= eigene Truppe"), ("friend", "Das Kreuz\n= Infanterie"),
                  ("friend", "Drei Punkte oben\n= Zug"), ("hostile", "Rote Raute\n= feindliche Truppe")],
        "build": "Selbst gebaut im\nTacticn-Baukasten",
        "end": "INFANTERIEZUG\n\nJedes Zeichen nach APP-6(D)\nals STL mit Magnet-Aussparung\n\nLink in Bio · tacticn.de",
        "caption": ("Weißt du, was dieses Zeichen bedeutet? 🎯\n\n"
                    "🟦 Blaues Rechteck = eigene Truppe\n✖️ Kreuz = Infanterie\n⚫⚫⚫ Drei Punkte = Zug\n"
                    "🟥 Rote Raute = feindliche Truppe\n\n"
                    "Folge 1 unserer Reihe „Zeichen erklärt“. Welches Zeichen sollen wir als Nächstes erklären? 👇\n\n"
                    "Alle Zeichen nach NATO APP-6(D) im Baukasten – als STL mit Magnet-Aussparung: Link in Bio.\n\n"
                    "#taktischezeichen #lagekarte #bundeswehr #reservisten #app6 #3ddruck #militär #tacticn"),
    },
}


def shots(ep, work: Path):
    """Scharfe Aufnahmen vom echten Baukasten: Zeichen je Zugehörigkeit + eine Gesamtansicht der Seite."""
    from playwright.sync_api import sync_playwright
    out = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 432, "height": 768}, device_scale_factor=2.5, locale="de-DE")
        page = ctx.new_page()
        page.goto(ep["url"], wait_until="networkidle", timeout=60000)
        for txt in ("Nur notwendige", "Ablehnen", "Alle ablehnen", "Nur erforderliche"):
            try:
                page.get_by_role("button", name=txt).first.click(timeout=1500)
                break
            except Exception:  # noqa: BLE001
                pass
        page.wait_for_timeout(1500)

        def choose(label, value):
            page.locator(f'select[aria-label="{label}"]').first.select_option(value)
            page.wait_for_timeout(900)

        def symbol(name):
            box = page.evaluate("""() => {
                let best = null, area = 0;
                for (const s of document.querySelectorAll('svg')) {
                    const r = s.getBoundingClientRect(); const a = r.width * r.height;
                    if (r.width > 60 && r.height > 40 && a > area) { area = a; best = s; }
                }
                if (!best) return null;
                best.scrollIntoView({block: 'center'});
                const r = best.getBoundingClientRect();
                return {x: r.left, y: r.top, width: r.width, height: r.height};
            }""")
            page.wait_for_timeout(400)
            if not box:
                raise RuntimeError("Zeichen nicht gefunden")
            pad = 10
            clip = {"x": max(0, box["x"] - pad), "y": max(0, box["y"] - pad), "width": box["width"] + 2 * pad,
                    "height": box["height"] + 2 * pad}
            page.screenshot(path=str(work / f"{name}.png"), clip=clip)
            out[name] = work / f"{name}.png"

        for label, value in ep.get("setup", []):
            choose(label, value)
        symbol("friend")
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(400)
        page.screenshot(path=str(work / "page.png"))
        out["page"] = work / "page.png"
        choose("Zugehörigkeit", "6")
        symbol("hostile")
        ctx.close()
        b.close()
    return out


def font(size, fonts_dir):
    from PIL import ImageFont
    for f in (Path(fonts_dir) / "Oswald.ttf", Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")):
        try:
            ft = ImageFont.truetype(str(f), size)
            try:
                ft.set_variation_by_axes([700])
            except Exception:  # noqa: BLE001
                pass
            return ft
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def frame(kind, img, text, tag, path: Path, fonts_dir):
    """1080x1920-Bild: Tacticn-Grün mit Raster, Zeichen groß, Text in Karte."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (W, H), GREEN)
    d = ImageDraw.Draw(im)
    for x in range(0, W, 60):
        d.line([(x, 0), (x, H)], fill=(67, 81, 51), width=2)
    for y in range(0, H, 60):
        d.line([(0, y), (W, y)], fill=(67, 81, 51), width=2)
    if img is not None:
        sym = Image.open(img).convert("RGB")
        if kind == "page":                          # Gesamtansicht wie ein Handy-Bildschirm
            sw = 700
            sym = sym.resize((sw, int(sym.height * sw / sym.width)))
            sym = sym.crop((0, 0, sw, min(sym.height, 1100)))
            x, y = (W - sw) // 2, 250
        else:
            sw = 900
            sym = sym.resize((sw, int(sym.height * sw / sym.width)))
            if sym.height > 900:
                sym = sym.resize((int(sym.width * 900 / sym.height), 900))
            x, y = (W - sym.width) // 2, 330 + (900 - sym.height) // 2
        d.rounded_rectangle([x - 16, y - 16, x + sym.width + 16, y + sym.height + 16], radius=30, fill=(20, 26, 16))
        im.paste(sym, (x, y))
    tf, ts = font(44, fonts_dir), 44
    while d.textlength(tag, font=tf) > W - 80 and ts > 24:
        ts -= 2
        tf = font(ts, fonts_dir)
    d.text((W // 2, 120), tag, font=tf, fill=TAN, anchor="mm")
    if text:
        lines = text.split("\n")
        size = 90 if kind != "end" else 72
        big = font(size, fonts_dir)
        while size > 40 and max(d.textlength(ln, font=big) for ln in lines) > W - 160:   # passt immer in die Breite
            size -= 4
            big = font(size, fonts_dir)
        lh = int(big.size * 1.2)
        centre = {"end": 900, "page": 1560}.get(kind, 1500)
        top = centre - lh * len(lines) // 2
        if kind != "end":
            wmax = max(d.textlength(ln, font=big) for ln in lines)
            d.rounded_rectangle([W / 2 - wmax / 2 - 50, top - 34, W / 2 + wmax / 2 + 50, top + lh * len(lines) + 16],
                                radius=26, fill=(26, 34, 21))
        for i, ln in enumerate(lines):
            d.text((W // 2, top + i * lh), ln, font=big, fill=(255, 255, 255) if kind != "end" else TAN, anchor="ma")
    im.save(path)


def music(work: Path):
    """CC0-Musik von Freesound (keine Namensnennung nötig); ohne Schlüssel: Stille."""
    key = os.environ.get("FREESOUND_API_KEY")
    if not key:
        return None
    r = requests.get("https://freesound.org/apiv2/search/text/", timeout=30, params={
        "query": "cinematic tension drums", "filter": 'license:"Creative Commons 0" duration:[25 TO 120]',
        "fields": "id,name,previews,license,duration", "sort": "rating_desc", "page_size": 8, "token": key})
    for s in r.json().get("results", []):
        if s.get("previews"):
            p = work / "music.mp3"
            p.write_bytes(requests.get(s["previews"]["preview-hq-mp3"], timeout=60).content)
            print("Musik:", s["name"], s["license"])
            return p
    return None


def compose(ep, imgs, work: Path, out: Path, fonts_dir):
    tag = f"ZEICHEN ERKLÄRT · FOLGE {ep['no']} · {ep['title'].upper()}"
    plan = [("hook", imgs["friend"], ep["hook"])]
    plan += [("step", imgs[k], t) for k, t in ep["steps"]]
    plan += [("page", imgs["page"], ep["build"]), ("end", None, ep["end"])]
    frames = []
    for i, (kind, img, txt) in enumerate(plan):
        f = work / f"f{i:02d}.png"
        frame(kind, img, txt, tag, f, fonts_dir)
        frames.append(f)
    n = len(frames)
    total = n * SEG - (n - 1) * XF
    args = ["ffmpeg", "-y", "-loglevel", "error"]
    for f in frames:
        args += ["-loop", "1", "-t", f"{SEG}", "-framerate", "30", "-i", str(f)]
    parts = []
    for i in range(n):                                 # sanftes Heranzoomen je Bild
        parts.append(f"[{i}:v]scale={W * 2}:{H * 2},zoompan=z='1+0.035*on/{int(SEG * 30)}':x='iw/2-(iw/zoom/2)':"
                     f"y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps=30,format=yuv420p[z{i}]")
    prev, acc = "[z0]", SEG
    for i in range(1, n):
        off = acc - XF
        parts.append(f"{prev}[z{i}]xfade=transition=fade:duration={XF}:offset={off:.2f}[x{i}]")
        prev, acc = f"[x{i}]", off + SEG
    mus = music(work)
    if mus:
        args += ["-stream_loop", "-1", "-i", str(mus)]
        parts.append(f"[{n}:a]atrim=0:{total:.2f},volume=0.55,afade=t=in:d=0.5,afade=t=out:st={total - 1.2:.2f}:d=1.2[a]")
    else:
        args += ["-f", "lavfi", "-t", f"{total:.2f}", "-i", "anullsrc=r=48000:cl=stereo"]
        parts.append(f"[{n}:a]anull[a]")
    args += ["-filter_complex", ";".join(parts), "-map", prev, "-map", "[a]", "-t", f"{total:.2f}", "-c:v", "libx264",
             "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
             "-movflags", "+faststart", str(out)]
    subprocess.run(args, check=True)
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", default="infanteriezug")
    ap.add_argument("--out", default="out")
    ap.add_argument("--fonts", default="fonts")
    a = ap.parse_args()
    ep = EPISODES[a.episode]
    out = Path(a.out).resolve()
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)
    imgs = shots(ep, work)
    mp4 = out / f"tacticn_{a.episode}.mp4"
    total = compose(ep, imgs, work, mp4, a.fonts)
    (out / f"tacticn_{a.episode}.txt").write_text(ep["caption"], encoding="utf-8")
    for k, v in imgs.items():
        (work / f"debug_{k}.png").write_bytes(v.read_bytes())
    print(f"::notice title=Tacticn-Reel::{mp4.name} {total:.1f} s")


if __name__ == "__main__":
    main()
