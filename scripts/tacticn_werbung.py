#!/usr/bin/env python3
"""
Tacticn – Werbeclip (Imagefilm, 9:16, ~22 s, ohne Stimme, CC0-Musik) mit echten Aufnahmen aus dem Baukasten.

  python scripts/tacticn_werbung.py --out out/ --fonts fonts

Ablauf: Hook → Zeichen-Montage (4 echte Zeichen, Name vom Baukasten) → 2x2-Raster → eigene vs. feindliche Truppe →
Baukasten-Ansicht → Nutzen (APP-6(D), STL mit Magnet-Aussparung) → Abspann mit tacticn.de.
Nur Aussagen, die schon auf tacticn.de stehen – keine Preise, keine Versprechen. Ergebnis landet zur Freigabe unter
Releases (tacticn-preview), es wird nichts gepostet.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tacticn_reel import GREEN, TAN, H, W, font  # noqa: E402

BASE = "https://tacticn.de"
WANT = ["10-1211", "10-1205", "10-1213", "10-1303"]   # Infanterie, Panzer, Aufklärung, Artillerie (falls vorhanden)
SEG, XF = 2.4, 0.3
DARK = (20, 26, 16)


def codes():
    try:
        xml = requests.get(f"{BASE}/sitemap.xml", timeout=30).text
        have = sorted(set(re.findall(r"/baukasten/(10-\d{4})<", xml)))
    except Exception:  # noqa: BLE001
        have = []
    pick = [c for c in WANT if c in have] if have else WANT[:]
    for c in have:                                          # auffüllen, falls Codes fehlen
        if len(pick) >= 4:
            break
        if not c.endswith("00") and c not in pick:
            pick.append(c)
    return pick[:4]


def capture(work: Path):
    from playwright.sync_api import sync_playwright
    out = {"symbols": []}
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 432, "height": 768}, device_scale_factor=2.5, locale="de-DE")
        page = ctx.new_page()

        def cookies():
            for _ in range(2):
                for txt in ("Nur notwendige", "Verstanden", "Ablehnen"):
                    try:
                        page.get_by_role("button", name=txt).first.click(timeout=1200)
                    except Exception:  # noqa: BLE001
                        pass
                page.wait_for_timeout(600)

        def symbol(path):
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
            page.screenshot(path=str(path), clip={"x": max(0, box["x"] - pad), "y": max(0, box["y"] - pad),
                                                  "width": box["width"] + 2 * pad, "height": box["height"] + 2 * pad})

        def choose(label, value):
            try:
                page.locator(f'select[aria-label="{label}"]').first.select_option(value, timeout=3000)
                page.wait_for_timeout(900)
                return True
            except Exception:  # noqa: BLE001
                return False

        for i, code in enumerate(codes()):
            try:
                page.goto(f"{BASE}/baukasten/{code}", wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(1200)
                cookies()
                name = page.evaluate("() => (document.querySelector('h1')||{}).innerText || ''").strip()
                name = re.sub(r"\s*[–|-]\s*Tacticn.*$", "", name)[:28] or code
                f = work / f"sym{i}.png"
                symbol(f)
                out["symbols"].append((name, f))
                if i == 0:                                   # Erstes Zeichen: auch feindlich + Gesamtansicht
                    page.evaluate("window.scrollTo(0, 0)")
                    page.wait_for_timeout(1000)
                    page.screenshot(path=str(work / "page.png"))
                    out["page"] = work / "page.png"
                    if choose("Zugehörigkeit", "6"):
                        symbol(work / "hostile.png")
                        out["hostile"] = work / "hostile.png"
            except Exception as e:  # noqa: BLE001
                print("Zeichen übersprungen:", code, e)
        ctx.close()
        b.close()
    if not out["symbols"]:
        raise RuntimeError("Keine Zeichen aufgenommen")
    return out


def canvas():
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (W, H), GREEN)
    d = ImageDraw.Draw(im)
    for x in range(0, W, 60):
        d.line([(x, 0), (x, H)], fill=(67, 81, 51), width=2)
    for y in range(0, H, 60):
        d.line([(0, y), (W, y)], fill=(67, 81, 51), width=2)
    d.rectangle([0, 0, W, 8], fill=TAN)
    d.rectangle([0, H - 8, W, H], fill=TAN)
    return im, d


def fit(d, lines, size, fonts_dir, maxw):
    f = font(size, fonts_dir)
    while size > 36 and max(d.textlength(ln, font=f) for ln in lines) > maxw:
        size -= 4
        f = font(size, fonts_dir)
    return f


def paste(im, d, path, cx, cy, maxw, maxh):
    from PIL import Image
    s = Image.open(path).convert("RGB")
    k = min(maxw / s.width, maxh / s.height)
    s = s.resize((int(s.width * k), int(s.height * k)))
    x, y = cx - s.width // 2, cy - s.height // 2
    d.rounded_rectangle([x - 16, y - 16, x + s.width + 16, y + s.height + 16], radius=28, fill=DARK)
    im.paste(s, (x, y))


def text(d, txt, cy, fonts_dir, size=86, color=(255, 255, 255), card=True):
    lines = txt.split("\n")
    f = fit(d, lines, size, fonts_dir, W - 170)
    lh = int(f.size * 1.2)
    top = cy - lh * len(lines) // 2
    if card:
        wmax = max(d.textlength(ln, font=f) for ln in lines)
        d.rounded_rectangle([W / 2 - wmax / 2 - 50, top - 30, W / 2 + wmax / 2 + 50, top + lh * len(lines) + 14],
                            radius=24, fill=(26, 34, 21))
    for i, ln in enumerate(lines):
        d.text((W // 2, top + i * lh), ln, font=f, fill=color, anchor="ma")


def tag(d, fonts_dir, t="TACTICN · TAKTISCHE ZEICHEN"):
    d.text((W // 2, 110), t, font=font(40, fonts_dir), fill=TAN, anchor="mm")


def frames(cap, work: Path, fonts_dir):
    plan = []
    sym = cap["symbols"]

    def save(im, name):
        p = work / f"{name}.png"
        im.save(p)
        plan.append(p)

    im, d = canvas(); tag(d, fonts_dir)                                  # 1 Hook
    paste(im, d, sym[0][1], W // 2, 820, 860, 760)
    text(d, "Deine Lage.\nPräzise dargestellt.", 1500, fonts_dir, 92)
    save(im, "w01")
    for i, (name, f) in enumerate(sym[1:4], 2):                          # 2-4 Montage
        im, d = canvas(); tag(d, fonts_dir)
        paste(im, d, f, W // 2, 820, 860, 760)
        text(d, name.upper(), 1500, fonts_dir, 84)
        save(im, f"w0{i}")
    im, d = canvas(); tag(d, fonts_dir)                                  # 5 Raster
    cells = [(W // 4 + 10, 620), (3 * W // 4 - 10, 620), (W // 4 + 10, 1080), (3 * W // 4 - 10, 1080)]
    for (name, f), (cx, cy) in zip(sym, cells):
        paste(im, d, f, cx, cy, 420, 360)
    text(d, "Jedes Zeichen\nnach NATO APP-6(D)", 1560, fonts_dir, 84)
    save(im, "w05")
    if cap.get("hostile"):                                               # 6 Freund / Feind
        im, d = canvas(); tag(d, fonts_dir)
        paste(im, d, sym[0][1], W // 2, 560, 640, 420)
        paste(im, d, cap["hostile"], W // 2, 1100, 640, 460)
        text(d, "Eigene oder feindliche\nTruppe – ein Klick", 1580, fonts_dir, 76)
        save(im, "w06")
    if cap.get("page"):                                                  # 7 Baukasten
        im, d = canvas(); tag(d, fonts_dir)
        from PIL import Image
        s = Image.open(cap["page"]).convert("RGB")
        sw = 700
        s = s.resize((sw, int(s.height * sw / s.width))).crop((0, 0, sw, min(int(s.height * sw / s.width), 1080)))
        x, y = (W - sw) // 2, 230
        d.rounded_rectangle([x - 18, y - 18, x + sw + 18, y + s.height + 18], radius=36, fill=DARK)
        im.paste(s, (x, y))
        text(d, "Selbst zusammenstellen\nim Tacticn-Baukasten", 1560, fonts_dir, 76)
        save(im, "w07")
    im, d = canvas(); tag(d, fonts_dir)                                  # 8 Nutzen
    text(d, "Als STL-Datei\nmit Magnet-Aussparung", 760, fonts_dir, 88)
    text(d, "Für Lagekarte,\nSandkasten & Ausbildung", 1240, fonts_dir, 72, TAN, card=False)
    save(im, "w08")
    im, d = canvas()                                                     # 9 Abspann
    text(d, "TACTICN", 760, fonts_dir, 190, TAN, card=False)
    text(d, "Taktische Zeichen.\nZum Anfassen.", 1060, fonts_dir, 70, (255, 255, 255), card=False)
    text(d, "tacticn.de", 1440, fonts_dir, 96)
    save(im, "w09")
    return plan


def music(work: Path):
    import os
    key = os.environ.get("FREESOUND_API_KEY")
    if not key:
        return None
    for q in ("epic cinematic trailer", "cinematic tension drums"):
        r = requests.get("https://freesound.org/apiv2/search/text/", timeout=30, params={
            "query": q, "filter": 'license:"Creative Commons 0" duration:[25 TO 150]',
            "fields": "id,name,previews,license", "sort": "rating_desc", "page_size": 8, "token": key})
        for s in r.json().get("results", []):
            if s.get("previews"):
                p = work / "music.mp3"
                p.write_bytes(requests.get(s["previews"]["preview-hq-mp3"], timeout=60).content)
                print("Musik:", s["name"], s["license"], f"https://freesound.org/s/{s['id']}/")
                return p
    return None


def compose(fr, work: Path, out: Path):
    n = len(fr)
    durs = [SEG] * n
    durs[0], durs[-1] = 2.8, 3.4
    total = sum(durs) - (n - 1) * XF
    args = ["ffmpeg", "-y", "-loglevel", "error"]
    for f, t in zip(fr, durs):
        args += ["-loop", "1", "-t", f"{t}", "-framerate", "30", "-i", str(f)]
    parts = []
    for i, t in enumerate(durs):
        z = "1+0.05*on/{0}".format(int(t * 30)) if i % 2 == 0 else "1.05-0.05*on/{0}".format(int(t * 30))
        parts.append(f"[{i}:v]scale={W * 2}:{H * 2},zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                     f"d=1:s={W}x{H}:fps=30,format=yuv420p[z{i}]")
    trans = ["slideleft", "fade", "slideleft", "fadeblack", "smoothup", "fade", "slideleft", "fadeblack"]
    prev, acc = "[z0]", durs[0]
    for i in range(1, n):
        off = acc - XF
        parts.append(f"{prev}[z{i}]xfade=transition={trans[(i - 1) % len(trans)]}:duration={XF}:offset={off:.2f}[x{i}]")
        prev, acc = f"[x{i}]", off + durs[i]
    mus = music(work)
    if mus:
        args += ["-stream_loop", "-1", "-i", str(mus)]
        parts.append(f"[{n}:a]atrim=0:{total:.2f},volume=0.6,afade=t=in:d=0.4,afade=t=out:st={total - 1.5:.2f}:d=1.5[a]")
    else:
        args += ["-f", "lavfi", "-t", f"{total:.2f}", "-i", "anullsrc=r=48000:cl=stereo"]
        parts.append(f"[{n}:a]anull[a]")
    args += ["-filter_complex", ";".join(parts), "-map", prev, "-map", "[a]", "-t", f"{total:.2f}", "-c:v", "libx264",
             "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart", str(out)]
    subprocess.run(args, check=True)
    return total


CAPTION = ("Deine Lage. Präzise dargestellt. 🎯\n\n"
           "Taktische Zeichen nach NATO APP-6(D) – selbst zusammengestellt im Tacticn-Baukasten und als STL-Datei "
           "mit Magnet-Aussparung für Lagekarte, Sandkasten und Ausbildung.\n\n"
           "👉 tacticn.de (Link in Bio)\n\n"
           "#taktischezeichen #lagekarte #bundeswehr #reservisten #app6 #3ddruck #tacticn")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    ap.add_argument("--fonts", default="fonts")
    a = ap.parse_args()
    out = Path(a.out).resolve()
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)
    cap = capture(work)
    fr = frames(cap, work, a.fonts)
    mp4 = out / "tacticn_werbeclip.mp4"
    total = compose(fr, work, mp4)
    (out / "tacticn_werbeclip.txt").write_text(CAPTION, encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1.5", "-i", str(mp4), "-frames:v", "1",
                    str(out / "tacticn_werbeclip_vorschau.jpg")], check=False)
    print(f"::notice title=Tacticn-Werbeclip::{mp4.name} {total:.1f} s")


if __name__ == "__main__":
    main()
