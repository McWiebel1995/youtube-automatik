"""
ClipWerk – Bildverständnis.

1. Lokal (immer): alle 2 s ein kleines Graustufenbild -> Schärfe, Helligkeit, Bewegung/Wackeln.
2. Gemini (optional): dieselben Momente als kleine Standbilder -> Was ist zu sehen? Wie interessant (1–10)?
   Es werden nur Standbilder (max. 384 px) geschickt, keine Videos und kein Ton.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from engine import Clip, data_dir, run, tool

STEP = 2.0            # Sekunden zwischen zwei Standbildern
GW, GH = 96, 160      # Größe für die lokale Messung (Graustufen)


@dataclass
class Shot:
    t: float
    sharp: float = 0.0      # 0..1
    bright: float = 0.0     # 0..1
    motion: float = 0.0     # 0..1 (Unterschied zum vorigen Bild)
    quality: float = 0.5    # 0..1 (aus den drei Werten)
    interest: float = 5.0   # 1..10 (Gemini, sonst aus Bewegung/Qualität geschätzt)
    kind: str = ""
    desc: str = ""


def _times(c: Clip):
    n = max(1, min(60, int(c.duration / STEP)))
    return [min(c.duration - 0.2, 0.5 + k * (c.duration - 1.0) / max(1, n - 1)) if n > 1 else c.duration / 2
            for k in range(n)]


def measure(c: Clip, log=print) -> list[Shot]:
    """Lokale Bildqualität: ein ffmpeg-Aufruf liefert alle Standbilder als Rohdaten."""
    ts = _times(c)
    w, h = (GW, GH) if c.vertical else (GH, GW)
    fps = len(ts) / max(1.0, c.duration)
    raw = run([tool("ffmpeg"), "-loglevel", "error", "-i", c.path, "-vf", f"fps={fps:.5f},scale={w}:{h},format=gray",
               "-f", "rawvideo", "-"], check=False).stdout or b""
    frames = np.frombuffer(raw, np.uint8)[: (len(raw) // (w * h)) * w * h].reshape(-1, h, w).astype(np.float32)
    shots, prev = [], None
    for k, f in enumerate(frames[: len(ts)]):
        lap = np.abs(4 * f[1:-1, 1:-1] - f[:-2, 1:-1] - f[2:, 1:-1] - f[1:-1, :-2] - f[1:-1, 2:])
        sharp = float(np.clip(lap.var() / 900.0, 0, 1))
        bright = float(f.mean() / 255.0)
        motion = float(np.clip(np.abs(f - prev).mean() / 40.0, 0, 1)) if prev is not None else 0.3
        prev = f
        q = sharp * 0.7 + (1 - abs(bright - 0.5) * 2) * 0.2 + (0.1 if motion < 0.8 else -0.25)
        shots.append(Shot(ts[k], sharp, bright, motion, float(np.clip(q, 0, 1)),
                          interest=float(np.clip(3 + 4 * sharp + 3 * min(motion, 0.6), 1, 10))))
    return shots


VISION_TASK = """Du bist Cutter für Instagram-Reels ({style}).
Hier sind Standbilder aus einem Handyvideo, jeweils mit Zeitpunkt in Sekunden.
Bewerte JEDES Bild: Was ist zu sehen (max. 8 Wörter, deutsch)? Wie interessant ist es für ein Reel (1–10)?
Hoch = Ergebnis/fertiges Werk, Vorher-Nachher, spannende Handarbeit in Aktion, Tiere, appetitliches Essen,
Nahaufnahme mit Details, Gesicht mit Emotion. Niedrig = leerer Boden, unscharf, verwackelt, Finger vor der Linse,
nichts passiert. kind ∈ ergebnis|vorher|aktion|detail|tier|essen|person|landschaft|langweilig.
Antworte NUR mit JSON: {{"shots":[{{"t":0.5,"desc":"...","interest":7,"kind":"aktion"}}]}}"""


def _jpeg_b64(c: Clip, t: float) -> str:
    w = 384 if not c.vertical else 216
    out = run([tool("ffmpeg"), "-loglevel", "error", "-ss", f"{t:.2f}", "-i", c.path, "-frames:v", "1",
               "-vf", f"scale={w}:-2", "-q:v", "6", "-f", "image2", "-c:v", "mjpeg", "-"], check=False).stdout
    return base64.b64encode(out or b"").decode()


def understand(c: Clip, shots: list[Shot], key: str, style: str, log=print) -> list[Shot]:
    """Gemini schaut sich die Standbilder an (in Paketen à 12). Ergebnis wird zwischengespeichert."""
    import requests
    st = c.path.stat()
    ck = data_dir() / "cache" / ("v_" + hashlib.md5(f"{c.path}|{st.st_size}|{st.st_mtime}|{STEP}".encode()).hexdigest() + ".json")
    if ck.exists():
        got = {round(x["t"], 1): x for x in json.loads(ck.read_text(encoding="utf-8"))}
    else:
        got = {}
        for k in range(0, len(shots), 12):
            batch = shots[k:k + 12]
            parts = [{"text": VISION_TASK.format(style=style)}]
            for s in batch:
                parts += [{"text": f"t={s.t:.1f}"}, {"inline_data": {"mime_type": "image/jpeg", "data": _jpeg_b64(c, s.t)}}]
            js = None
            for model in ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash"):
                try:
                    r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                      params={"key": key}, timeout=120,
                                      json={"contents": [{"parts": parts}],
                                            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}})
                    if r.status_code in (404, 400):
                        continue
                    if r.status_code == 429:
                        time.sleep(6)
                        continue
                    r.raise_for_status()
                    txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                    js = json.loads(re.sub(r"^```(json)?|```$", "", txt.strip()))
                    break
                except Exception as e:  # noqa: BLE001
                    log(f"  (Bildanalyse {model}: {str(e)[:80]})")
            for x in (js or {}).get("shots", []):
                try:
                    got[round(float(x["t"]), 1)] = x
                except Exception:  # noqa: BLE001
                    pass
        ck.parent.mkdir(parents=True, exist_ok=True)
        ck.write_text(json.dumps(list(got.values()), ensure_ascii=False), encoding="utf-8")
    for s in shots:
        x = got.get(round(s.t, 1)) or min(got.values(), key=lambda v: abs(float(v.get("t", 0)) - s.t), default=None)
        if x and abs(float(x.get("t", 0)) - s.t) < STEP:
            s.desc = str(x.get("desc", ""))[:60]
            s.kind = str(x.get("kind", ""))
            s.interest = float(np.clip(float(x.get("interest", 5)), 1, 10))
    return shots


def score_at(shots: list[Shot], a: float, b: float) -> tuple[float, float, str]:
    """(Interesse, Qualität, Beschreibung) für den Abschnitt a..b."""
    inside = [s for s in shots if a - STEP / 2 <= s.t <= b + STEP / 2] or \
             ([min(shots, key=lambda s: abs(s.t - (a + b) / 2))] if shots else [])
    if not inside:
        return 5.0, 0.5, ""
    best = max(inside, key=lambda s: s.interest)
    return (float(np.mean([s.interest for s in inside]) * 0.5 + best.interest * 0.5),
            float(np.mean([s.quality for s in inside])), best.desc)


def best_windows(shots: list[Shot], duration: float, n: int, length=3.0) -> list[tuple[float, float]]:
    """Die n stärksten Bildmomente (ohne Überlappung) als Zeitfenster – für Zwischenschnitte ohne Sprache."""
    ranked = sorted(shots, key=lambda s: s.interest * (0.4 + s.quality), reverse=True)
    top = ranked[0].interest if ranked else 5
    out = []
    for s in ranked:
        if s.quality < 0.25 or (out and s.interest < max(4.0, top * 0.6)):   # Schwaches nur, wenn sonst nichts da ist
            continue
        a = max(0.0, min(duration - length, s.t - length / 2))
        if all(abs(a - x) >= length for x, _ in out):
            out.append((a, a + length))
        if len(out) >= n:
            break
    return sorted(out)


_ = Path
