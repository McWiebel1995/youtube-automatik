#!/usr/bin/env python3
"""Lädt freie Schriften (SIL Open Font License) aus dem Google-Fonts-Repo nach assets/fonts/."""
import os
import sys
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent.parent / "assets" / "fonts"
FONTS = {   # Ordner im Repo google/fonts -> Dateiname bei uns
    "fredoka": "Fredoka.ttf", "baloo2": "Baloo2.ttf", "nunito": "Nunito.ttf", "quicksand": "Quicksand.ttf",
    "sniglet": "Sniglet.ttf", "chewy": "Chewy.ttf", "patrickhand": "PatrickHand.ttf", "pacifico": "Pacifico.ttf",
    "dancingscript": "DancingScript.ttf", "playfairdisplay": "PlayfairDisplay.ttf", "montserrat": "Montserrat.ttf",
    "cormorantgaramond": "CormorantGaramond.ttf", "bangers": "Bangers.ttf", "anton": "Anton.ttf",
    "lilitaone": "LilitaOne.ttf", "comfortaa": "Comfortaa.ttf", "poppins": "Poppins-ExtraBold.ttf", "cinzel": "Cinzel.ttf",
}
PICK = {"poppins": "Poppins-ExtraBold.ttf"}   # bestimmte Datei statt variabler Schrift
H = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"} if os.environ.get("GITHUB_TOKEN") else {}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for folder, name in FONTS.items():
        dst = OUT / name
        if dst.exists() and dst.stat().st_size > 10000:
            continue
        try:
            r = requests.get(f"https://api.github.com/repos/google/fonts/contents/ofl/{folder}", headers=H, timeout=30)
            r.raise_for_status()
            ttfs = [f for f in r.json() if f["name"].endswith(".ttf") and "Italic" not in f["name"]]
            # bevorzugt die variable Schrift ([wght]) oder Regular/ExtraBold
            ttfs.sort(key=lambda f: (0 if "[" in f["name"] else 1 if "Regular" in f["name"] else 2))
            if folder in PICK:
                ttfs = [f for f in ttfs if f["name"] == PICK[folder]] or ttfs
            dst.write_bytes(requests.get(ttfs[0]["download_url"], timeout=60).content)
            print(f"  ✓ {name} ({ttfs[0]['name']})")
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ {folder}: {e}", file=sys.stderr)
    kids = OUT / "Kids.ttf"
    if not kids.exists() and (OUT / "Fredoka.ttf").exists():
        kids.write_bytes((OUT / "Fredoka.ttf").read_bytes())


if __name__ == "__main__":
    main()
