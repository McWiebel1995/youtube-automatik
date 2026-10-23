#!/usr/bin/env python3
"""
Lädt ECHTE Natur-Videos von Pixabay und/oder Pexels (beide kostenlos, kommerziell nutzbar,
keine Namensnennung nötig) und macht daraus nahtlose 1080p-Loops (bis 120 s, Schnitt an der ähnlichsten Stelle).

Kostenlose API-Schlüssel (einer reicht, beide = mehr Auswahl):
  Pixabay: https://pixabay.com/api/docs/      -> Secret PIXABAY_API_KEY
  Pexels:  https://www.pexels.com/api/        -> Secret PEXELS_API_KEY

    python scripts/fetch_stock.py --per-channel 8

Sobald echte Clips vorhanden sind, nimmt die Pipeline sie bevorzugt (siehe render.py).
Der Ton bleibt immer unsere eigene Mischung.
"""
import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import requests

sys.path.insert(0, os.path.dirname(__file__))
from common import ASSETS, duration, ffmpeg  # noqa: E402

# Suchbegriff -> Szenenname für den (englischen) Titel
QUERIES = {
    "regen": {
        "rain window": "Rain on Window", "raindrops on glass": "Rain on Window",
        "rain forest": "Rain in the Forest", "rain leaves": "Rain in the Forest",
        "rain city night": "Rainy Night in the City", "rain street": "Rainy Night in the City",
        "rain puddle": "Rain on the Porch", "rain lake": "Rain on the Lake",
    },
    "kamin": {
        "fireplace": "Country House Fireplace", "fireplace cozy": "Autumn Evening by the Fire",
        "campfire night": "Campfire by the Lake", "bonfire": "Campfire by the Lake",
        "fire logs burning": "Snowy Cabin Fireplace", "fire wood burning": "Country House Fireplace",
    },
    "wasserfall": {
        "waterfall": "Mountain Waterfall", "waterfall forest": "Rainforest Waterfall",
        "waterfall jungle": "Rainforest Waterfall", "mountain stream": "Gentle Forest Stream",
        "forest creek": "Gentle Forest Stream", "waterfall mist": "Misty Morning Waterfall",
    },
}
MAX_LOOP = 120      # maximale Loop-Länge in Sekunden (länger = Wiederholung fällt weniger auf)
MIN_CLIP = 15       # kürzere Clips werden gar nicht erst geladen
XFADE = 0.6         # kurze Überblendung an der besten Schnittstelle
MAX_DIFF = 14       # Clips, deren Ende nie zum Anfang passt (z. B. Kamerafahrt), werden verworfen


def best_loop_point(src):
    """Sucht die Stelle, an der das Bild dem ersten Bild am ähnlichsten ist -> unsichtbarer Schnitt."""
    import subprocess

    import numpy as np
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(src), "-t", str(MAX_LOOP + 5),
                          "-vf", "fps=10,scale=64:36,format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    f = np.frombuffer(raw, np.uint8).reshape(-1, 36, 64).astype(np.float32)
    if len(f) < MIN_CLIP * 10:
        raise ValueError("Clip zu kurz")
    lo = max(int(len(f) * 0.5), 80)
    cand = range(lo, len(f) - 2)
    # Ähnlichkeit von Bild + Bewegung: zwei aufeinanderfolgende Bilder vergleichen
    score = [np.abs(f[i] - f[0]).mean() + np.abs(f[i + 1] - f[1]).mean() for i in cand]
    i = int(np.argmin(score))
    best = score[i] / 2
    if best > MAX_DIFF:
        raise ValueError(f"kein sauberer Loop möglich (Abweichung {best:.1f})")
    return (lo + i) / 10.0, best


def make_loop(src, dst):
    """Schneidet an der besten Stelle und überblendet ganz kurz -> nahtlose Wiederholung."""
    t_best, diff = best_loop_point(src)
    c = XFADE
    d = min(t_best + c, duration(src) - 0.05)
    flt = (
        "[0:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,fps=30,"
        "format=yuv420p,split[s1][s2];"
        f"[s1]trim={c}:{d},setpts=PTS-STARTPTS[a];"
        f"[s2]trim=0:{c},setpts=PTS-STARTPTS[b];"
        f"[a][b]xfade=transition=fade:duration={c}:offset={d - 2 * c},format=yuv420p[v]"
    )
    ffmpeg("-i", src, "-filter_complex", flt, "-map", "[v]", "-an", "-c:v", "libx264", "-profile:v", "high",
           "-level", "4.1", "-pix_fmt", "yuv420p", "-preset", "slow", "-crf", "23", "-maxrate", "4500k", "-bufsize", "9000k",
           "-g", "60", "-movflags", "+faststart", dst)
    return d - c, diff


# ----------------------------------------------------------------- Quellen
CREEPY = {"spider", "spiders", "insect", "insects", "bug", "bugs", "snake", "snakes", "worm", "worms", "ant", "ants",
          "bee", "bees", "wasp", "cockroach", "tarantula", "scorpion", "mosquito", "fly", "flies", "beetle", "caterpillar",
          "people", "person", "man", "woman", "girl", "boy", "crowd", "face", "car", "traffic"}


def _creepy(text):
    import re
    return bool(CREEPY & set(re.findall(r"[a-z]+", (text or "").lower())))


def search_pixabay(key, q):
    r = requests.get("https://pixabay.com/api/videos/", timeout=30, params={
        "key": key, "q": q, "per_page": 30, "safesearch": "true", "order": "popular"})
    r.raise_for_status()
    hits = sorted(r.json().get("hits", []), key=lambda h: -h.get("duration", 0))
    for hit in hits:
        if hit.get("duration", 0) < MIN_CLIP or _creepy(hit.get("tags", "")):
            continue
        v = hit["videos"].get("large") or hit["videos"].get("medium") or {}
        if v.get("url") and v.get("width", 0) >= 1920:
            yield f"pixabay_{hit['id']}", v["url"], hit.get("user", "")


def search_pexels(key, q):
    r = requests.get("https://api.pexels.com/videos/search", timeout=30, headers={"Authorization": key},
                     params={"query": q, "per_page": 30, "orientation": "landscape", "size": "large"})
    r.raise_for_status()
    vids = sorted(r.json().get("videos", []), key=lambda v: -v.get("duration", 0))
    for vid in vids:
        if vid.get("duration", 0) < MIN_CLIP or _creepy(vid.get("url", "").replace("-", " ")):
            continue
        files = [f for f in vid.get("video_files", []) if (f.get("width") or 0) >= 1920
                 and f.get("file_type") == "video/mp4"]
        if files:
            best = min(files, key=lambda f: f["width"])  # 1080p statt 4K -> schneller
            yield f"pexels_{vid['id']}", best["link"], (vid.get("user") or {}).get("name", "")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--per-channel", type=int, default=8)
    ap.add_argument("--channels", nargs="*", default=list(QUERIES))
    args = ap.parse_args()

    sources = []
    if os.environ.get("PIXABAY_API_KEY"):
        sources.append(("Pixabay", search_pixabay, os.environ["PIXABAY_API_KEY"]))
    if os.environ.get("PEXELS_API_KEY"):
        sources.append(("Pexels", search_pexels, os.environ["PEXELS_API_KEY"]))
    if not sources:
        print("Kein PIXABAY_API_KEY / PEXELS_API_KEY gesetzt – nutze nur selbst gezeichnete Szenen.")
        return

    for chan in args.channels:
        out_dir = ASSETS / chan / "video"
        out_dir.mkdir(parents=True, exist_ok=True)
        need = args.per_channel - len(list(out_dir.glob("pixabay_*.mp4")) + list(out_dir.glob("pexels_*.mp4")))
        # Suchbegriffe reihum, damit die Szenen gemischt werden
        for q, scene in list(QUERIES[chan].items()) * 2:
            if need <= 0:
                break
            for src_name, search, key in sources:
                if need <= 0:
                    break
                try:
                    hits = list(search(key, q))
                except requests.RequestException as e:
                    print(f"  ⚠ {src_name} '{q}': {e}")
                    continue
                for clip_id, url, author in hits:
                    dst = out_dir / f"{clip_id}.mp4"
                    if dst.exists():
                        continue
                    with tempfile.NamedTemporaryFile(suffix=".mp4") as tmp:
                        try:
                            with requests.get(url, stream=True, timeout=180) as dl:
                                dl.raise_for_status()
                                for chunk in dl.iter_content(1 << 20):
                                    tmp.write(chunk)
                            tmp.flush()
                            part = dst.with_name(dst.name + ".part.mp4")
                            length, diff = make_loop(tmp.name, part)
                            part.replace(dst)
                        except Exception as e:  # noqa: BLE001
                            print(f"  übersprungen {clip_id}: {e}")
                            dst.unlink(missing_ok=True)
                            continue
                    dst.with_suffix(".json").write_text(json.dumps(
                        {"scene": scene, "query": q, "source": src_name, "author": author}, ensure_ascii=False))
                    print(f"  ✓ {chan}: {clip_id} – {scene} ({src_name}, {author}) – Loop {length:.0f}s, Abweichung {diff:.1f}")
                    need -= 1
                    time.sleep(0.5)
                    break  # pro Suchbegriff und Quelle ein Clip -> mehr Abwechslung


if __name__ == "__main__":
    main()
