#!/usr/bin/env python3
"""
Tacticn – Quiz-Reels: genau EIN Zeichen pro Video, aus dem ganzen Tacticn-Baukasten (tacticn.de).

  python scripts/tacticn_quiz.py --symbol zufall --out out/    # nächstes noch nicht benutztes Zeichen
  python scripts/tacticn_quiz.py --symbol 10-1211 --out out/   # bestimmtes Zeichen
  python scripts/tacticn_quiz.py --probe                       # Baukasten untersuchen – nur Log

Pool: alle Baukasten-Seiten aus tacticn.de/sitemap.xml (Symbolbereich 10 = Land-Einheiten). Bereits benutzte
Zeichen stehen in data/tacticn_quiz_used.json, damit sich nichts wiederholt. Name und Antwortmöglichkeiten kommen
direkt vom Baukasten (Überschrift + Liste „Truppengattung / Art“) – also immer passend zur Seite.

Ablauf im Video (~16 s, ohne Stimme, CC0-Musik):
  Frage (Zeichen groß) → 3 Antworten mit Countdown 3-2-1 → Auflösung → „Wie viele hattest du?“ + tacticn.de
"""
import argparse
import json
import random
import re
import subprocess
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tacticn_reel import GREEN, TAN, H, W, font, music  # noqa: E402

BASE = "https://tacticn.de"
USED = Path(__file__).resolve().parent.parent / "data" / "tacticn_quiz_used.json"
LETTERS = "ABC"
OK_GREEN, BAD_GREY = (92, 170, 70), (88, 96, 80)
SKIP_OPT = re.compile(r"Versorgungsklasse|^US|Bundes|Behörde|Ministerium|Marshals|Geheimdienst|\(FBI\)|\(TSA\)|"
                      r"Alliiert|Internationale|Gemeinsame|Benanntes|^Kampf$|Kampftruppen|Multinational")


# ---------------------------------------------------------------- Pool
def pool(symbol_set="10"):
    xml = requests.get(f"{BASE}/sitemap.xml", timeout=30).text
    codes = sorted(set(re.findall(rf"/baukasten/({symbol_set}-\d{{4}})<", xml)))
    return [c for c in codes if not c.endswith("00")]   # xx00 = Oberbegriff (leeres Rechteck) – nicht ratbar


def load_used():
    try:
        return json.loads(USED.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def pick(symbol, codes, used):
    if symbol and symbol != "zufall":
        return symbol
    done = {u["code"] for u in used}
    fresh = [c for c in codes if c not in done] or codes          # Pool durch → von vorn
    return random.choice(fresh)


# ---------------------------------------------------------------- Baukasten
def capture(code, work: Path):
    """Zeichen hochauflösend aufnehmen + Name, Kategorie und mögliche Falschantworten von der Seite lesen."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 432, "height": 768}, device_scale_factor=2.5, locale="de-DE")
        page = ctx.new_page()
        page.goto(f"{BASE}/baukasten/{code}", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(1500)
        for _ in range(2):                                   # Cookie-Hinweis (kommt teils verzögert)
            for txt in ("Nur notwendige", "Verstanden"):
                try:
                    page.get_by_role("button", name=txt).first.click(timeout=1500)
                except Exception:  # noqa: BLE001
                    pass
            page.wait_for_timeout(800)
        info = page.evaluate("""() => {
            const h = [...document.querySelectorAll('h1,h2')].map(e => e.innerText.trim()).filter(Boolean);
            const sel = [...document.querySelectorAll('select')].find(s =>
                (s.getAttribute('aria-label') || '').startsWith('Truppengattung'));
            const lines = document.body.innerText.split('\\n').map(s => s.trim());
            return {name: h[0] || '', category: lines.find(l => /^[A-ZÄÖÜ-]+ \\/ /.test(l)) || '',
                    options: sel ? [...sel.options].map(o => o.text.trim()) : []};
        }""")
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
        if not box or not info["name"]:
            raise RuntimeError(f"{code}: Zeichen oder Name nicht gefunden")
        pad = 10
        img = work / "symbol.png"
        page.screenshot(path=str(img), clip={"x": max(0, box["x"] - pad), "y": max(0, box["y"] - pad),
                                             "width": box["width"] + 2 * pad, "height": box["height"] + 2 * pad})
        ctx.close()
        b.close()
    info["image"] = img
    return info


def choices(name, options):
    cands = sorted({o for o in options if o and o != name and len(o) <= 30 and not SKIP_OPT.search(o)
                    and o.split()[0] != name.split()[0]})
    wrong = random.sample(cands, 2)
    opts = wrong + [name]
    random.shuffle(opts)
    return opts


# ---------------------------------------------------------------- Bilder
def base(tag, fonts_dir):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (W, H), GREEN)
    d = ImageDraw.Draw(im)
    for x in range(0, W, 60):
        d.line([(x, 0), (x, H)], fill=(67, 81, 51), width=2)
    for y in range(0, H, 60):
        d.line([(0, y), (W, y)], fill=(67, 81, 51), width=2)
    tf, ts = font(44, fonts_dir), 44
    while d.textlength(tag, font=tf) > W - 80 and ts > 24:
        ts -= 2
        tf = font(ts, fonts_dir)
    d.text((W // 2, 110), tag, font=tf, fill=TAN, anchor="mm")
    return im, d


def paste_symbol(im, d, img, top, box_h):
    from PIL import Image
    sym = Image.open(img).convert("RGB")
    sw = 820
    sym = sym.resize((sw, int(sym.height * sw / sym.width)))
    if sym.height > box_h:
        sym = sym.resize((int(sym.width * box_h / sym.height), box_h))
    x, y = (W - sym.width) // 2, top + (box_h - sym.height) // 2
    d.rounded_rectangle([x - 16, y - 16, x + sym.width + 16, y + sym.height + 16], radius=30, fill=(20, 26, 16))
    im.paste(sym, (x, y))


def fit(d, text, size, maxw, fonts_dir, minsize=34):
    f = font(size, fonts_dir)
    while size > minsize and d.textlength(text, font=f) > maxw:
        size -= 2
        f = font(size, fonts_dir)
    return f


def card(d, text, y, fonts_dir, size=86, fill=(26, 34, 21), color=(255, 255, 255)):
    f = fit(d, text, size, W - 200, fonts_dir)
    w = d.textlength(text, font=f)
    d.rounded_rectangle([W / 2 - w / 2 - 50, y - 70, W / 2 + w / 2 + 50, y + 70], radius=26, fill=fill)
    d.text((W // 2, y), text, font=f, fill=color, anchor="mm")


def frame_question(q, tag, path, fonts_dir):
    im, d = base(tag, fonts_dir)
    paste_symbol(im, d, q["image"], 260, 860)
    card(d, "Was bedeutet", 1330, fonts_dir, 92)
    card(d, "dieses Zeichen?", 1490, fonts_dir, 92)
    d.text((W // 2, 1680), "Antworten kommen gleich", font=font(46, fonts_dir), fill=TAN, anchor="mm")
    im.save(path)


def frame_options(q, tag, path, fonts_dir, count=None, reveal=False):
    im, d = base(tag, fonts_dir)
    paste_symbol(im, d, q["image"], 220, 640)
    of = None
    for i, opt in enumerate(q["options"]):
        y = 1010 + i * 175
        right = opt == q["name"]
        fill = (OK_GREEN if right else BAD_GREY) if reveal else (26, 34, 21)
        d.rounded_rectangle([90, y - 72, W - 90, y + 72], radius=28, fill=fill,
                            outline=(255, 255, 255) if reveal and right else TAN, width=5 if reveal and right else 2)
        d.ellipse([120, y - 46, 212, y + 46], fill=TAN)
        d.text((166, y), LETTERS[i], font=font(58, fonts_dir), fill=GREEN, anchor="mm")
        of = fit(d, opt, 64, W - 360, fonts_dir, 30)
        col = (255, 255, 255) if (not reveal or right) else (190, 196, 180)
        d.text((250, y), opt, font=of, fill=col, anchor="lm")
    if count is not None:
        d.ellipse([W // 2 - 95, 1560, W // 2 + 95, 1750], fill=TAN)
        d.text((W // 2, 1655), str(count), font=font(130, fonts_dir), fill=GREEN, anchor="mm")
    if reveal:
        card(d, f"RICHTIG: {q['name'].upper()}", 1660, fonts_dir, 70, fill=(20, 26, 16), color=TAN)
    im.save(path)


def frame_end(q, tag, path, fonts_dir):
    im, d = base(tag, fonts_dir)
    paste_symbol(im, d, q["image"], 230, 520)
    lines = [("Hattest du es richtig?", 84, (255, 255, 255)), ("Schreib's in die Kommentare!", 60, TAN),
             ("", 30, TAN), ("Jedes Zeichen nach APP-6(D)", 58, (255, 255, 255)),
             ("als STL mit Magnet-Aussparung", 58, (255, 255, 255)), ("", 30, TAN), ("Link in Bio · tacticn.de", 66, TAN)]
    y = 1000
    for txt, size, col in lines:
        if txt:
            d.text((W // 2, y), txt, font=fit(d, txt, size, W - 140, fonts_dir), fill=col, anchor="mm")
        y += int(size * 1.45)
    im.save(path)


# ---------------------------------------------------------------- Video
def compose(q, no, work: Path, out: Path, fonts_dir):
    tag = f"TACTICN-QUIZ · #{no} · ERKENNST DU ES?"
    plan = [("q", 2.8, lambda p: frame_question(q, tag, p, fonts_dir), True)]
    for c in (3, 2, 1):
        plan.append((f"c{c}", 1.4, lambda p, c=c: frame_options(q, tag, p, fonts_dir, count=c), False))
    plan.append(("r", 3.2, lambda p: frame_options(q, tag, p, fonts_dir, reveal=True), True))
    plan.append(("e", 3.6, lambda p: frame_end(q, tag, p, fonts_dir), True))
    xf = 0.25
    args, parts, durs = ["ffmpeg", "-y", "-loglevel", "error"], [], []
    for i, (key, dur, make, zoom) in enumerate(plan):
        f = work / f"q{i:02d}_{key}.png"
        make(f)
        durs.append(dur)
        args += ["-loop", "1", "-t", f"{dur}", "-framerate", "30", "-i", str(f)]
        z = f"1+0.03*on/{int(dur * 30)}" if zoom else "1"
        parts.append(f"[{i}:v]scale={W * 2}:{H * 2},zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                     f"d=1:s={W}x{H}:fps=30,format=yuv420p[z{i}]")
    prev, acc = "[z0]", durs[0]
    for i in range(1, len(plan)):
        off = acc - xf
        parts.append(f"{prev}[z{i}]xfade=transition=fade:duration={xf}:offset={off:.2f}[x{i}]")
        prev, acc = f"[x{i}]", off + durs[i]
    total = acc
    n = len(plan)
    mus = music(work)
    if mus:
        args += ["-stream_loop", "-1", "-i", str(mus)]
        parts.append(f"[{n}:a]atrim=0:{total:.2f},volume=0.55,afade=t=in:d=0.4,afade=t=out:st={total - 1:.2f}:d=1[a]")
    else:
        args += ["-f", "lavfi", "-t", f"{total:.2f}", "-i", "anullsrc=r=48000:cl=stereo"]
        parts.append(f"[{n}:a]anull[a]")
    args += ["-filter_complex", ";".join(parts), "-map", prev, "-map", "[a]", "-t", f"{total:.2f}", "-c:v", "libx264",
             "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
             "-movflags", "+faststart", str(out)]
    subprocess.run(args, check=True)
    return total


def caption(q, no):
    opts = "\n".join(f"{LETTERS[i]}) {o}" for i, o in enumerate(q["options"]))
    right = LETTERS[q["options"].index(q["name"])]
    return (f"Tacticn-Quiz #{no}: Was bedeutet dieses Zeichen? 🎯\n\n{opts}\n\n"
            f"Schreib deine Antwort in die Kommentare 👇 (Auflösung im Video: {right})\n\n"
            "Alle Zeichen nach NATO APP-6(D) im Baukasten – als STL mit Magnet-Aussparung: Link in Bio.\n\n"
            "#taktischezeichen #quiz #lagekarte #bundeswehr #reservisten #app6 #3ddruck #militär #tacticn")


# ---------------------------------------------------------------- Probe (Fehlersuche)
def probe(url):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 432, "height": 768}, locale="de-DE")
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(2500)
        info = page.evaluate("""() => ({
            headings: [...document.querySelectorAll('h1,h2,h3')].map(h => h.innerText),
            selects: [...document.querySelectorAll('select')].map(s => [s.getAttribute('aria-label'), s.options.length]),
            text: document.body.innerText.slice(0, 1500)})""")
        print(json.dumps(info, ensure_ascii=False, indent=1))
        b.close()
    print("Pool:", len(pool()), "Zeichen")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--symbol", default="zufall")
    ap.add_argument("--out", default="out")
    ap.add_argument("--fonts", default="fonts")
    a = ap.parse_args()
    if a.probe:
        probe(f"{BASE}/baukasten/10-1211")
        return
    out = Path(a.out).resolve()
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)
    used = load_used()
    codes = pool()
    print(f"Pool: {len(codes)} Zeichen, schon benutzt: {len(used)}")
    for attempt in range(4):                       # einzelne kaputte Seiten überspringen
        code = pick(a.symbol, codes, used)
        try:
            q = capture(code, work)
            q["options"] = choices(q["name"], q["options"])
            break
        except Exception as e:  # noqa: BLE001
            print(f"::warning::{code} übersprungen: {e}")
            if a.symbol != "zufall" or attempt == 3:
                raise
            used.append({"code": code, "name": "", "skip": True})
    no = len([u for u in used if not u.get("skip")]) + 1
    print(f"Zeichen {code}: {q['name']} ({q['category']}) · Antworten: {q['options']}")
    stem = f"tacticn_quiz_{no:03d}_{code}"
    mp4 = out / f"{stem}.mp4"
    total = compose(q, no, work, mp4, a.fonts)
    (out / f"{stem}.txt").write_text(caption(q, no), encoding="utf-8")
    used.append({"code": code, "name": q["name"], "no": no, "options": q["options"]})
    USED.parent.mkdir(parents=True, exist_ok=True)
    USED.write_text(json.dumps(used, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"::notice title=Tacticn-Quiz #{no}::{q['name']} ({code}) · {mp4.name} {total:.1f} s")


if __name__ == "__main__":
    main()
