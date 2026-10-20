#!/usr/bin/env python3
"""Schriftproben als Bild: output/fonts.png"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
fonts = sorted((ROOT / "assets/fonts").glob("*.ttf"))
fonts = [f for f in fonts if f.name != "Kids.ttf"]
row, W = 150, 1600
img = Image.new("RGB", (W, row * len(fonts) + 40), (24, 26, 52))
d = ImageDraw.Draw(img)
for i, f in enumerate(fonts):
    y = 20 + i * row
    d.text((30, y + 8), f"{i + 1}. {f.stem}", font=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 26),
           fill=(150, 150, 190))
    ft = ImageFont.truetype(str(f), 64)
    for wname in ("Bold", "SemiBold", "ExtraBold"):
        try:
            ft.set_variation_by_name(wname)
            break
        except Exception:  # noqa: BLE001
            pass
    d.text((30, y + 48), "Gute Nacht, kleiner Stern 3 HOURS Rain", font=ft, fill=(255, 244, 214))
(ROOT / "output").mkdir(exist_ok=True)
img.save(ROOT / "output/fonts.png")
print("ok", len(fonts))
