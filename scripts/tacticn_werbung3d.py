#!/usr/bin/env python3
"""
Tacticn – Werbeclip „3D“ (9:16, ~20 s, ohne Stimme, CC0-Musik): das echte 3D-Druckmodell aus dem Baukasten dreht sich.

  python scripts/tacticn_werbung3d.py --out out/ --fonts fonts

Ablauf: Hook mit drehendem 3D-Modell → Name des Zeichens → Unterseite mit Prägung (Magnet innen) → feindliche Truppe in 3D →
fertige Sets → Abspann. Nur Aussagen, die auf tacticn.de stehen, keine Preise. Ergebnis kommt zur Freigabe nach
Releases (tacticn-preview), gepostet wird hier nichts.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tacticn_reel import TAN, H, W, font  # noqa: E402
from tacticn_werbung import BASE, canvas, music, tag, text  # noqa: E402

FPS = 30
CODE = "10-1211"                 # Infanterie (Grundgefecht) – im Baukasten vorhanden
TURN = 60                        # Aufnahmen pro volle Drehung


def capture(work: Path, code: str = CODE):
    from playwright.sync_api import sync_playwright
    cap = {}
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
                                    "--ignore-gpu-blocklist"])
        ctx = b.new_context(viewport={"width": 432, "height": 768}, device_scale_factor=2.5, locale="de-DE")
        page = ctx.new_page()

        def cookies():
            for txt in ("Nur notwendige", "Verstanden", "Ablehnen"):
                try:
                    page.get_by_role("button", name=txt).first.click(timeout=1200)
                except Exception:  # noqa: BLE001
                    pass

        def choose(label, value):
            page.locator(f'select[aria-label="{label}"]').first.select_option(value, timeout=4000)
            page.wait_for_timeout(2500)

        def turntable(prefix, n, sweep=1.0):
            """Dreht das Modell per Maus (OrbitControls) und nimmt jeden Schritt auf."""
            cv = page.locator("canvas").first
            cv.scroll_into_view_if_needed()
            page.wait_for_timeout(800)
            box = cv.bounding_box()
            cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            step = box["height"] * sweep / n          # OrbitControls: Drehung 2π je Canvas-Höhe
            pad = 6
            clip = {"x": box["x"] + pad, "y": box["y"] + pad, "width": box["width"] - 2 * pad, "height": box["height"] - 2 * pad}
            files = []
            for i in range(n):
                f = work / f"{prefix}_{i:03d}.png"
                for k in range(3):                    # SwiftShader hängt bei manchen Modellen kurz -> neu versuchen
                    try:
                        page.screenshot(path=str(f), clip=clip, timeout=90000, animations="disabled", caret="hide")
                        files.append(f)
                        break
                    except Exception as e:  # noqa: BLE001
                        print("Aufnahme hängt, neuer Versuch:", i, repr(e)[:80])
                        page.wait_for_timeout(2000)
                page.mouse.move(cx, cy)
                page.mouse.down()
                page.mouse.move(cx + step, cy, steps=3)
                page.mouse.up()
                page.wait_for_timeout(120)
            return files

        page.goto(f"{BASE}/baukasten/{code}", wait_until="networkidle", timeout=60000)
        cookies()
        page.wait_for_timeout(1500)
        cookies()
        try:
            choose("Einheitsebene", "15")             # Kompanie
        except Exception as e:  # noqa: BLE001
            print("Einheitsebene nicht gesetzt:", e)
        page.wait_for_timeout(5000)                   # 3D-Modell wird im Browser berechnet
        name = page.evaluate("() => (document.querySelector('h1')||{}).innerText || ''").strip()
        cap["name"] = re.sub(r"\s*[–|-]\s*Tacticn.*$", "", name).split("/")[0].strip()[:30] or "Infanterie"
        cap["friend"] = turntable("fr", TURN)
        try:
            page.get_by_role("button", name="Unterseite zeigen").click(timeout=4000)
            page.wait_for_timeout(3000)
            cap["under"] = turntable("un", 36, 0.6)
            page.get_by_role("button", name="Oberseite zeigen").click(timeout=4000)
        except Exception as e:  # noqa: BLE001
            print("Unterseite nicht aufgenommen:", e)
        try:
            choose("Zugehörigkeit", "6")
            page.wait_for_timeout(4000)
            cap["hostile"] = turntable("ho", 36, 0.6)
        except Exception as e:  # noqa: BLE001
            print("Feind nicht aufgenommen:", e)
        page.goto(f"{BASE}/sets", wait_until="networkidle", timeout=60000)
        cookies()
        page.wait_for_timeout(1500)
        page.screenshot(path=str(work / "sets.png"), full_page=True)
        cap["sets"] = work / "sets.png"
        ctx.close()
        b.close()
    print("Aufnahmen:", {k: (len(v) if isinstance(v, list) else v) for k, v in cap.items()})
    return cap


def crop_model(s):
    """Modell größer zeigen und den Knopf „Unterseite/Oberseite zeigen“ unten rechts abschneiden."""
    w, h = s.size
    return s.crop((int(w * 0.13), int(h * 0.10), int(w * 0.87), int(h * 0.84)))


def model_frame(img_path, caption, small=None, fonts_dir="fonts", title="TACTICN · 3D-DRUCKMODELL"):
    from PIL import Image
    im, d = canvas()
    tag(d, fonts_dir, title)
    s = crop_model(Image.open(img_path).convert("RGB"))
    k = min(960 / s.width, 1000 / s.height)
    s = s.resize((int(s.width * k), int(s.height * k)), Image.LANCZOS)
    x, y = (W - s.width) // 2, 230 + (1000 - s.height) // 2
    d.rounded_rectangle([x - 14, y - 14, x + s.width + 14, y + s.height + 14], radius=30, fill=(20, 26, 16))
    im.paste(s, (x, y))
    text(d, caption, 1440, fonts_dir, 84)
    if small:
        text(d, small, 1660, fonts_dir, 52, TAN, card=False)
    return im


def build(cap, out: Path, fonts_dir, hook="Dein Lagezeichen.\nIn 3D.", stem="tacticn_werbeclip_3d"):
    from PIL import Image
    segs = []                                          # (Dauer s, Funktion t->Bild)
    fr = cap["friend"]
    name = cap["name"].upper()

    def spin(files, fps_cap=12):
        return lambda t: files[int(t * fps_cap) % len(files)]
    segs.append((2.6, lambda t, f=spin(fr): model_frame(f(t), hook, None, fonts_dir)))
    segs.append((3.0, lambda t, f=spin(fr): model_frame(f(t + 2.6), name, "nach NATO APP-6(D)", fonts_dir)))
    if cap.get("under"):
        segs.append((3.0, lambda t, f=spin(cap["under"]): model_frame(f(t), "Mit TACTICN-Prägung\nauf der Unterseite", "Magnet-Aussparung im Inneren", fonts_dir)))
    if cap.get("hostile"):
        segs.append((3.0, lambda t, f=spin(cap["hostile"]): model_frame(f(t), "Eigene oder\nfeindliche Truppe", "ein Klick im Baukasten", fonts_dir)))
    sets = Image.open(cap["sets"]).convert("RGB")
    sw = 860
    sets = sets.resize((sw, int(sets.height * sw / sets.width)), Image.LANCZOS)

    def sets_frame(t):
        im, d = canvas()
        tag(d, fonts_dir, "TACTICN · FERTIGE SETS")
        view = 1060
        maxoff = max(0, sets.height - view)
        off = int(min(maxoff, maxoff * (t / 3.2) * 0.6))
        crop = sets.crop((0, off, sw, off + min(view, sets.height)))
        x, y = (W - sw) // 2, 200
        d.rounded_rectangle([x - 14, y - 14, x + sw + 14, y + crop.height + 14], radius=30, fill=(20, 26, 16))
        im.paste(crop, (x, y))
        text(d, "Komplette Sets –\nvon Jägerkompanie bis OPFOR", 1480, fonts_dir, 72)
        return im
    segs.append((3.2, sets_frame))

    def end_frame(t, f=spin(fr)):
        im, d = canvas()
        s = crop_model(Image.open(f(t)).convert("RGB"))
        k = 520 / s.width
        s = s.resize((520, int(s.height * k)), Image.LANCZOS)
        im.paste(s, ((W - 520) // 2, 260))
        text(d, "TACTICN", 1080, fonts_dir, 170, TAN, card=False)
        text(d, "Als STL – selbst drucken,\nauf die Lagekarte stellen.", 1320, fonts_dir, 62, (255, 255, 255), card=False)
        text(d, "tacticn.de", 1560, fonts_dir, 96)
        return im
    segs.append((3.4, end_frame))

    total = sum(s[0] for s in segs)
    mp4 = out / f"{stem}.mp4"
    work = out / "work"
    mus = music(work)
    args = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
    if mus:
        args += ["-stream_loop", "-1", "-i", str(mus), "-af",
                 f"atrim=0:{total:.2f},volume=0.6,afade=t=in:d=0.4,afade=t=out:st={total - 1.5:.2f}:d=1.5"]
    else:
        args += ["-f", "lavfi", "-t", f"{total:.2f}", "-i", "anullsrc=r=48000:cl=stereo"]
    args += ["-map", "0:v", "-map", "1:a", "-t", f"{total:.2f}", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(mp4)]
    proc = subprocess.Popen(args, stdin=subprocess.PIPE)
    from PIL import Image as _I
    prev = None
    for dur, fn in segs:
        n = int(dur * FPS)
        for i in range(n):
            t = i / FPS
            im = fn(t)
            if prev is not None and i < 8:              # kurze Überblendung zwischen Abschnitten
                im = _I.blend(prev, im, (i + 1) / 9)
            proc.stdin.write(im.tobytes())
            last = im
        prev = last
    proc.stdin.close()
    proc.wait()
    return mp4, total


CAPTION = ("Dein Lagezeichen. In 3D. 🎯\n\n"
           "Jedes taktische Zeichen nach NATO APP-6(D) wird im Tacticn-Baukasten direkt zum 3D-Druckmodell – "
           "mit Magnet-Aussparung im Inneren und TACTICN-Prägung auf der Unterseite. Eigene oder feindliche Truppe, einzeln oder als komplettes Set "
           "von der Jägerkompanie bis zur Feinddarstellung.\n\n"
           "Als STL herunterladen, selbst drucken, auf die Lagekarte stellen.\n\n"
           "👉 tacticn.de (Link in Bio)\n\n"
           "#taktischezeichen #lagekarte #sandkasten #bundeswehr #reservisten #app6 #3ddruck #stl #tacticn")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    ap.add_argument("--fonts", default="fonts")
    ap.add_argument("--code", default=CODE)
    ap.add_argument("--hook", default="Dein Lagezeichen.\\nIn 3D.")
    ap.add_argument("--stem", default="tacticn_werbeclip_3d")
    a = ap.parse_args()
    hook = a.hook.replace("\\n", "\n")
    out = Path(a.out).resolve()
    work = out / "work"
    import shutil
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    cap = capture(work, a.code)
    mp4, total = build(cap, out, a.fonts, hook, a.stem)
    name = cap["name"]
    cap_txt = CAPTION.replace("Dein Lagezeichen. In 3D. 🎯", f"{hook.replace(chr(10), ' ')} 🎯\n\n{name} als 3D-Druckmodell.")
    (out / f"{a.stem}.txt").write_text(cap_txt, encoding="utf-8")
    print(f"::notice title=Tacticn-Werbeclip 3D::{mp4.name} {name} {total:.1f} s")


if __name__ == "__main__":
    main()
