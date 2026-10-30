#!/usr/bin/env python3
"""Beispiel-Thumbnails für alle Kanäle rendern (zum Ansehen, lädt nichts hoch) -> output/thumbs/"""
import random
import sys
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "anime")]
import covers  # noqa: E402
import thumbs  # noqa: E402

OUT = HERE.parent / "output" / "thumbs"
OUT.mkdir(parents=True, exist_ok=True)
rnd = random.Random(7)


def stock(q, name):
    c = covers._pexels(q, "landscape") or covers._pixabay(q, "landscape", "photo")
    print(f"{q}: {len(c)} Treffer")
    p = OUT / f"bg_{name}.jpg"
    p.write_bytes(requests.get(c[rnd.randrange(min(5, len(c)))][1], timeout=60).content)
    return p


thumbs.whatif(stock("planet earth from space dramatic", "w1"), "What If Earth Stopped Spinning?", OUT / "whatif_1.jpg")
thumbs.whatif(stock("black hole space", "w2"), "What if a black hole passed through you?", OUT / "whatif_2.jpg")
for ch, scene, h in (("regen", "Rain on Window", 3), ("kamin", "Cabin Fireplace", 2), ("wasserfall", "Forest Stream", 1)):
    bg = covers.background(ch, scene, "landscape", OUT, rnd)
    thumbs.calm(bg, ch, h, thumbs.calm_hook(ch, rnd), OUT / f"calm_{ch}.jpg")
bg = covers.background("schlaf", "Sternenhimmel Mond", "landscape", OUT, rnd)
thumbs.kids(bg, "schlaf", "Spieluhr unter dem Sternenhimmel", "15 MIN", OUT / "kids_schlaf.jpg", rnd)
bg = covers.background("geschichten", "Finni Faultier und der warme Sand", "landscape", OUT, rnd)
thumbs.kids(bg, "geschichten", "Finni Faultier und der warme Sand", "GUTE NACHT", OUT / "kids_geschichten.jpg", rnd)
print("\n".join(str(p) for p in sorted(OUT.glob("*.jpg")) if not p.name.startswith(("bg_", "cover_"))))
