#!/usr/bin/env python3
"""
Tacticn – Story-Bilder (9:16) zu den fertigen Reels: morgens Teaser, abends Auflösung bzw. STL-Hinweis.

  python scripts/tacticn_storys.py --reels entwuerfe/ --out storys/ --fonts fonts

Liest je Reel <stem>.mp4 + <stem>.txt (Bildunterschrift) und baut:
  Quiz:  <stem>_morgen.png  (Zeichen + Antworten, „Auflösung heute 18 Uhr im Reel“)
         <stem>_abend.png   (richtige Antwort grün, „Wusstest du's?“)
  3D:    <stem>_morgen.png  (drehendes Modell, „Heute 18 Uhr: … in 3D“)
         <stem>_abend.png   (Feind-Variante, „Als STL – selbst drucken“)
Alles aus den Reel-Bildern selbst, keine neuen Aussagen. Gepostet wird hier nichts.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tacticn_reel import TAN  # noqa: E402
from tacticn_werbung import canvas, tag, text  # noqa: E402

SAFE_TOP, SAFE_BOTTOM = 250, 1670          # Instagram blendet oben/unten Profil und Antwortfeld ein


def grab(mp4: Path, t: float, out: Path):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t}", "-i", str(mp4), "-frames:v", "1", str(out)], check=True)
    from PIL import Image
    return Image.open(out).convert("RGB")


def place(im, d, crop, top, maxw=900, maxh=900, frame=True):
    from PIL import Image
    k = min(maxw / crop.width, maxh / crop.height)
    crop = crop.resize((int(crop.width * k), int(crop.height * k)), Image.LANCZOS)
    x = (im.width - crop.width) // 2
    if frame:
        d.rounded_rectangle([x - 14, top - 14, x + crop.width + 14, top + crop.height + 14], radius=30, fill=(20, 26, 16))
    im.paste(crop, (x, top))
    return top + crop.height


def quiz(stem, mp4, cap, out, fonts, work):
    no = re.search(r"Quiz #(\d+)", cap).group(1)
    # Morgens: Frage mit Antworten (ohne Countdown-Zahl)
    f = grab(mp4, 4.6, work / f"{stem}_q.png")
    im, d = canvas()
    tag(d, fonts, f"TACTICN-QUIZ #{no} · HEUTE 18 UHR")
    bottom = place(im, d, f.crop((60, 150, 1020, 1450)), SAFE_TOP + 20, 900, 1000, frame=False)
    text(d, "Was bedeutet\ndieses Zeichen?", bottom + 150, fonts, 84)
    text(d, "Auflösung heute um 18 Uhr im Reel", min(bottom + 330, SAFE_BOTTOM - 20), fonts, 50, TAN, card=False)
    im.save(out / f"{stem}_morgen.png")
    # Abends: richtige Antwort
    f = grab(mp4, 7.6, work / f"{stem}_a.png")
    im, d = canvas()
    tag(d, fonts, f"TACTICN-QUIZ #{no} · AUFLÖSUNG")
    bottom = place(im, d, f.crop((60, 150, 1020, 1740)), SAFE_TOP + 10, 900, 1080, frame=False)
    text(d, "Wusstest du's?", bottom + 110, fonts, 80)
    text(d, "Das ganze Quiz im Reel · tacticn.de", min(bottom + 250, SAFE_BOTTOM - 20), fonts, 48, TAN, card=False)
    im.save(out / f"{stem}_abend.png")


def drei_d(stem, mp4, cap, out, fonts, work):
    name = re.search(r"\n\n(.+?) als 3D-Druckmodell", cap).group(1).strip()
    box = (60, 360, 1020, 1100)                                  # Modellfenster im Reel
    f = grab(mp4, 0.6, work / f"{stem}_m.png")
    im, d = canvas()
    tag(d, fonts, "TACTICN · HEUTE 18 UHR")
    bottom = place(im, d, f.crop(box), SAFE_TOP + 80, 960, 800)
    text(d, f"{name}\nin 3D", bottom + 220, fonts, 96)
    text(d, "Neues Reel heute um 18 Uhr", min(bottom + 440, SAFE_BOTTOM - 20), fonts, 52, TAN, card=False)
    im.save(out / f"{stem}_morgen.png")
    f = grab(mp4, 10.2, work / f"{stem}_f.png")                # Feind-Variante (rot)
    im, d = canvas()
    tag(d, fonts, "TACTICN · 3D-DRUCKMODELL")
    bottom = place(im, d, f.crop(box), SAFE_TOP + 80, 960, 800)
    text(d, "Eigene oder feindliche Truppe –\nals STL selbst drucken", bottom + 220, fonts, 70)
    text(d, "tacticn.de · Link in Bio", min(bottom + 430, SAFE_BOTTOM - 20), fonts, 60, TAN, card=False)
    im.save(out / f"{stem}_abend.png")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reels", default="entwuerfe")
    ap.add_argument("--out", default="storys")
    ap.add_argument("--fonts", default="fonts")
    a = ap.parse_args()
    src, out = Path(a.reels), Path(a.out)
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)
    n = 0
    for mp4 in sorted(src.glob("tacticn_*.mp4")):
        txt = mp4.with_suffix(".txt")
        if not txt.exists():
            continue
        cap = txt.read_text(encoding="utf-8")
        try:
            (quiz if "_quiz_" in mp4.stem else drei_d)(mp4.stem, mp4, cap, out, a.fonts, work)
            n += 2
        except Exception as e:  # noqa: BLE001
            print(f"::warning::Story {mp4.stem} fehlgeschlagen: {e!r}")
    print(f"::notice title=Tacticn-Storys::{n} Bilder")


if __name__ == "__main__":
    main()
