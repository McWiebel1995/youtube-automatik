#!/usr/bin/env python3
"""
Lädt ECHTE Natur-Aufnahmen von Freesound.org – nur Lizenz CC0 (gemeinfrei, kommerziell nutzbar,
keine Namensnennung nötig) – und macht daraus nahtlose Sound-Loops.

Kostenloser API-Schlüssel: https://freesound.org/apiv2/apply  -> Secret FREESOUND_API_KEY

    python scripts/fetch_sounds.py --per-sound 3

Die echten Aufnahmen werden in der Pipeline bevorzugt; die selbst erzeugten Sounds
bleiben als Reserve und werden nur noch selten verwendet.
"""
import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import requests
from scipy.io import wavfile

sys.path.insert(0, os.path.dirname(__file__))
from common import ASSETS, load_config  # noqa: E402
from gen_audio import SR, seamless, write_flac  # noqa: E402

# Datei-Präfix -> Suchbegriffe (englisch, Freesound ist international)
QUERIES = {
    "rain_": ["rain ambience", "gentle rain", "rain on window", "rain forest ambience"],
    "roof_": ["rain on roof", "rain on tin roof", "rain on tent"],
    "thunder_": ["distant thunder rain", "thunderstorm ambience"],
    "wind_": ["wind ambience", "soft wind trees", "wind howling cabin"],
    "fire_": ["fireplace crackling", "campfire crackling", "fire crackling close"],
    "clock_": ["clock ticking", "grandfather clock ticking"],
    "waterfall_": ["waterfall", "waterfall ambience", "cascade water"],
    "stream_": ["stream creek", "babbling brook", "river gentle"],
    "birds_": ["birds forest ambience", "morning birdsong", "birds chirping nature"],
}
BAD_TAGS = {"music", "voice", "speech", "talking", "melody", "song", "synth", "processed", "loop-music"}
# Störende Geräusche, die in Natur-Aufnahmen oft mit drin sind (Tiere, Menschen, Verkehr) – geprüft in
# Tags, Titel und Beschreibung. Vögel sind nur beim "birds_"-Sound erlaubt.
NOISE_WORDS = {"sheep", "lamb", "lambs", "goat", "cow", "cows", "cattle", "farm", "barn", "dog", "dogs", "bark",
               "barking", "rooster", "chicken", "chickens", "hen", "horse", "donkey", "pig", "cat", "meow", "animal",
               "animals", "frog", "frogs", "cricket", "crickets", "insects", "people", "person", "children", "kids",
               "child", "baby", "voices", "crowd", "laugh", "cough", "footsteps", "car", "cars", "traffic", "siren",
               "motorbike", "airplane", "plane", "train", "bell", "bells", "church", "tractor", "lawnmower",
               "city", "street", "streets", "road", "urban", "highway", "engine", "motor", "vehicle", "vehicles",
               "truck", "bus", "tram", "horn", "construction", "drill", "radio", "tv", "television", "talk", "talking",
               "neighbour", "neighbor", "neighbourhood", "parking", "garage", "door", "doors", "window-cleaner",
               "helicopter", "jet", "beep", "alarm", "phone", "kitchen", "cafe", "restaurant", "station", "subway"}
BIRD_WORDS = {"bird", "birds", "birdsong", "chirp", "chirping", "crow", "owl", "seagull", "gull", "duck", "geese"}


def _words(s):
    import re
    text = " ".join([s.get("name", ""), s.get("description", ""), " ".join(s.get("tags", []))]).lower()
    return set(re.findall(r"[a-zäöü]+", text))


def search(key, query, allow_birds=False):
    params = {
        "query": query, "token": key, "page_size": 30, "sort": "rating_desc",
        "filter": 'license:"Creative Commons 0" duration:[60 TO 1500] avg_rating:[3.5 TO *]',
        "fields": "id,name,tags,description,duration,previews,username,num_downloads,avg_rating",
    }
    r = requests.get("https://freesound.org/apiv2/search/text/", timeout=30, params=params)
    if r.status_code == 404:  # neuere API-Version
        r = requests.get("https://freesound.org/apiv2/search/", timeout=30, params=params)
    r.raise_for_status()
    for s in r.json().get("results", []):
        if BAD_TAGS & {t.lower() for t in s.get("tags", [])}:
            continue
        w = _words(s)
        if w & NOISE_WORDS or (not allow_birds and w & BIRD_WORDS):
            continue
        pv = s.get("previews") or {}
        url = pv.get("preview-hq-ogg") or pv.get("preview-hq-mp3")   # ogg = 192 kbit/s
        if url:
            yield s, url


def to_loop(mp3_path, out_path, max_seconds=300, prefix=""):
    """Dekodiert, schneidet Anfang/Ende weg, normalisiert und macht einen nahtlosen Loop."""
    with tempfile.NamedTemporaryFile(suffix=".wav") as wav:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp3_path, "-ac", "2", "-ar", str(SR),
                        "-af", "highpass=f=25", wav.name], check=True)
        _, data = wavfile.read(wav.name)
    x = data.astype(np.float32) / 32768
    x = x[int(2 * SR): -int(2 * SR)] if len(x) > 20 * SR else x       # Ein-/Ausblendungen weg
    if len(x) < 40 * SR:
        raise ValueError("zu kurz")
    x = x[: int(max_seconds * SR) + 4 * SR]
    fade = 4 * SR
    loop_n = len(x) - fade
    # Lautstärke-Ausreißer (Klopfen, Husten …) prüfen: sehr laute Spitzen gegenüber dem Mittel
    win = SR // 2
    m = x[: len(x) // win * win].mean(axis=1).reshape(-1, win)
    rms = np.sqrt((m ** 2).mean(axis=1)) + 1e-9
    if np.percentile(rms, 99.5) / np.median(rms) > 8:          # länger anhaltende laute Störung (Stimme, Auto, Hund …)
        raise ValueError("laute Störgeräusche im Ton")
    if car_like(x, prefix):
        raise ValueError("Anschwellen im Tiefton (vermutlich Auto/Motor)")
    if gemini_clean(x, prefix) is False:
        raise ValueError("Gemini hört Störgeräusche")
    write_flac(out_path, seamless(x, loop_n, fade))


def car_like(x, prefix):
    """Vorbeifahrende Autos/Motoren: deutliches, mehrsekündiges Anschwellen im Tiefton (40–250 Hz).
    Regen/Feuer/Wasser sind dort gleichmäßig. Donner/Wind sind ausgenommen (die schwellen natürlich an)."""
    if prefix in ("thunder_", "wind_"):
        return False
    mono = x.mean(axis=1)
    win = SR // 2
    n = len(mono) // win
    if n < 20:
        return False
    frames = mono[: n * win].reshape(n, win) * np.hanning(win)
    spec = np.abs(np.fft.rfft(frames, axis=1)) ** 2
    f = np.fft.rfftfreq(win, 1 / SR)
    low = spec[:, (f >= 40) & (f <= 250)].sum(axis=1)
    tot = spec.sum(axis=1) + 1e-12
    share = np.convolve(low / tot, np.ones(4) / 4, "same")          # 2-s-Glättung
    return float(np.percentile(share, 97) / (np.median(share) + 1e-9)) > 3.0


GEMINI_LISTEN = ("You are checking a nature sound recording for a sleep-sounds video. Expected sound: {what}. "
                 "Listen carefully to all of it. Is it ONLY that sound (plus natural ambience like soft wind)? List any "
                 "unwanted sounds: cars, traffic, engines, airplanes, voices, people, footsteps, doors, animals, "
                 "insects, music, beeps, phones, clicks, hum, wind noise on the microphone. "
                 'Answer ONLY JSON: {{"clean": true/false, "unwanted": ["..."]}}')
WHAT = {"rain_": "steady rain", "roof_": "rain on a roof or tent", "thunder_": "rain with distant thunder",
        "wind_": "wind", "fire_": "a crackling fireplace or campfire", "clock_": "a ticking clock",
        "waterfall_": "a waterfall", "stream_": "a stream or brook", "birds_": "birds in a forest"}


def gemini_clean(x, prefix):
    """Gemini hört 3 Ausschnitte (Anfang/Mitte/Ende, je 20 s). True = sauber, False = Störgeräusch, None = keine Prüfung."""
    import base64
    import json
    import re
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    n = len(x)
    parts = [x[int(n * a): int(n * a) + 20 * SR] for a in (0.05, 0.45, 0.8)]
    clip = np.concatenate([p for p in parts if len(p)])
    with tempfile.TemporaryDirectory() as d:
        wavp, mp3p = Path(d) / "c.wav", Path(d) / "c.mp3"
        wavfile.write(wavp, SR, (np.clip(clip, -1, 1) * 32767).astype(np.int16))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wavp), "-ac", "1", "-ar", "16000", "-b:a", "48k",
                        str(mp3p)], check=True)
        b64 = base64.b64encode(mp3p.read_bytes()).decode()
    for model in ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-2.5-flash"):
        try:
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                              params={"key": key}, timeout=120, json={
                                  "contents": [{"parts": [{"text": GEMINI_LISTEN.format(what=WHAT.get(prefix, "nature sound"))},
                                                          {"inline_data": {"mime_type": "audio/mp3", "data": b64}}]}],
                                  "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}})
            if r.status_code in (404, 400):
                continue
            if r.status_code == 429:
                time.sleep(8)
                continue
            r.raise_for_status()
            js = json.loads(re.sub(r"^```(json)?|```$", "", r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()))
            if not js.get("clean", False):
                print(f"    🎧 Gemini hört Störgeräusche: {', '.join(js.get('unwanted', []))[:120]}")
            return bool(js.get("clean", False))
        except Exception as e:  # noqa: BLE001
            print(f"    (Hörprobe {model}: {str(e)[:80]})")
    return None


def prefixes_for(chan, cfg):
    layers = cfg["channels"][chan]["layers"]
    pats = [layers["base"]["pattern"]] + [e["pattern"] for e in layers.get("extras", [])]
    return [p.rstrip("*") for p in pats]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--per-sound", type=int, default=3, help="echte Aufnahmen pro Sound-Art")
    ap.add_argument("--channels", nargs="*")
    args = ap.parse_args()
    key = os.environ.get("FREESOUND_API_KEY")
    if not key:
        print("Kein FREESOUND_API_KEY gesetzt – nutze nur selbst erzeugte Sounds.")
        return
    cfg = load_config()
    for chan in args.channels or list(cfg["channels"]):
        out_dir = ASSETS / chan / "audio"
        out_dir.mkdir(parents=True, exist_ok=True)
        for prefix in prefixes_for(chan, cfg):
            have = len(list(out_dir.glob(f"{prefix}fs*.flac")))
            need = args.per_sound - have
            for q in QUERIES.get(prefix, []):
                if need <= 0:
                    break
                try:
                    hits = list(search(key, q, allow_birds=prefix == "birds_"))
                except requests.RequestException as e:
                    print(f"  ⚠ Freesound '{q}': {e}")
                    continue
                for s, url in hits:
                    dst = out_dir / f"{prefix}fs{s['id']}.flac"
                    if dst.exists():
                        continue
                    with tempfile.NamedTemporaryFile(suffix=".ogg" if url.endswith(".ogg") else ".mp3") as tmp:
                        try:
                            r = requests.get(url, timeout=120)
                            r.raise_for_status()
                            tmp.write(r.content)
                            tmp.flush()
                            to_loop(tmp.name, dst, prefix=prefix)
                        except Exception as e:  # noqa: BLE001
                            print(f"  übersprungen {s['id']}: {e}")
                            dst.unlink(missing_ok=True)
                            continue
                    print(f"  ✓ {chan}: {dst.name} – „{s['name']}“ von {s['username']} ({s['duration']:.0f}s)")
                    need -= 1
                    time.sleep(0.5)
                    break  # pro Suchbegriff eine Aufnahme -> mehr Abwechslung


if __name__ == "__main__":
    main()
