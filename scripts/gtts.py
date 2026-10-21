"""Gemini-TTS (High-End-Stimmen, Gratis-Kontingent). Gemeinsam für Kinderkanäle und „Ruhige Gedanken“."""
import base64
import os
import time
import wave

import numpy as np
import requests
from scipy.io import wavfile
from scipy.signal import resample_poly

MODELS = ["gemini-2.5-flash-preview-tts", "gemini-2.5-flash-tts", "gemini-2.5-pro-preview-tts"]
STYLE_STORY = ("Lies wie eine liebevolle, erfahrene Erzählerin eine Gute-Nacht-Geschichte für kleine Kinder vor: "
               "ruhig, warm und lebendig, bei wörtlicher Rede etwas Ausdruck, mit kleinen natürlichen Pausen. "
               "Lies den folgenden Text vor:\n\n")


def synth(text, voice, out_wav, style=STYLE_STORY, key=None):
    """Schreibt WAV (24 kHz mono). Gibt das benutzte Modell zurück; Fehler -> RuntimeError."""
    key = key or os.environ["GEMINI_API_KEY"]
    last = None
    for m in MODELS:
        for attempt in range(4):
            body = {"contents": [{"parts": [{"text": style + text}]}],
                    "generationConfig": {"responseModalities": ["AUDIO"],
                                         "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
                              headers={"x-goog-api-key": key}, json=body, timeout=300)
            if r.status_code == 200:
                try:
                    data = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
                except (KeyError, IndexError):
                    last = f"{m}: keine Audiodaten"
                    break
                with wave.open(str(out_wav), "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(24000)
                    w.writeframes(base64.b64decode(data))
                return m
            last = f"{m}: {r.status_code} {r.text[:200]}"
            if r.status_code == 429:
                if "per day" in r.text.lower() or "PerDay" in r.text:
                    break                               # Tageslimit dieses Modells -> nächstes Modell
                time.sleep(25 * (attempt + 1))
                continue
            if r.status_code in (500, 502, 503, 504):
                time.sleep(10)
                continue
            break
    raise RuntimeError(f"Gemini-TTS fehlgeschlagen: {last}")


def read(path, sr_out):
    sr, a = wavfile.read(path)
    a = a.astype(np.float32) / 32768
    if a.ndim > 1:
        a = a.mean(axis=1)
    return resample_poly(a, sr_out, sr).astype(np.float32) if sr != sr_out else a


def trim(a, sr, thr=0.004):
    idx = np.where(np.abs(a) > thr)[0]
    return a[max(0, idx[0] - sr // 60): idx[-1] + sr // 20] if len(idx) else a


def chunks(paragraphs, max_words=280):
    out, cur = [], []
    for p in paragraphs:
        if cur and len(" ".join(cur + [p]).split()) > max_words:
            out.append(cur)
            cur = []
        cur.append(p)
    if cur:
        out.append(cur)
    return out


def spoken_with_timing(blocks, voice, work, sr, split_sentences, gap=1.2, style=STYLE_STORY, lead=2.0):
    """blocks = Liste von Textstücken (je eine TTS-Anfrage). Gibt (audio, subs[(start,end,satz)], modell) zurück.
    Satz-Zeiten werden innerhalb eines Stücks proportional zur Zeichenlänge geschätzt."""
    pieces, subs, t, model = [np.zeros(int(lead * sr), np.float32)], [], lead, None
    for i, text in enumerate(blocks):
        f = work / f"g_{i:02d}.wav"
        model = synth(text, voice, f, style)
        a = trim(read(f, sr), sr)
        f.unlink(missing_ok=True)
        d = len(a) / sr
        sents = split_sentences(text)
        total_chars = sum(len(s) for s in sents) or 1
        cur = t
        for s in sents:
            dur = d * len(s) / total_chars
            subs.append((cur, cur + dur, s))
            cur += dur
        pieces += [a, np.zeros(int(gap * sr), np.float32)]
        t += d + gap
        time.sleep(1.5)
    return np.concatenate(pieces), subs, model
