#!/usr/bin/env python3
"""Hörproben verschiedener Stimmen (gleicher Text) -> output/voices/*.mp3"""
import base64
import io
import os
import subprocess
import sys
import wave
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output" / "voices"
OUT.mkdir(parents=True, exist_ok=True)
TEXT = ("Es war einmal ein kleiner Igel, der wohnte am Rand eines großen Waldes. Jeden Abend, wenn die Sonne "
        "unterging, schaute er hinauf zu den Sternen und flüsterte: Gute Nacht, ihr kleinen Lichter. "
        "Und weißt du was? Heute Nacht antwortete ihm zum ersten Mal ein Stern.")
notes = []


def to_mp3(wav_path, name):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path), "-ar", "44100", "-b:a", "160k",
                    "-af", "loudnorm=I=-16:TP=-1.5", str(OUT / f"{name}.mp3")], check=True)


# 1) aktuell: Piper (offline)
sys.path.insert(0, str(ROOT / "scripts" / "kids"))
try:
    import tts
    for v in ["de_DE-thorsten-medium", "de_DE-thorsten-high", "de_DE-kerstin-low"]:
        tts.speak(TEXT, OUT / "tmp.wav", v, 0.92)
        to_mp3(OUT / "tmp.wav", f"1_piper_{v.split('-')[1]}_{v.split('-')[2]}")
except Exception as e:  # noqa: BLE001
    notes.append(f"Piper: {e}")

# 2) Gemini TTS (Gratis-Kontingent, Stil per Anweisung)
key = os.environ.get("GEMINI_API_KEY")
models = ["gemini-2.5-flash-preview-tts", "gemini-2.5-flash-tts", "gemini-2.5-pro-preview-tts"]
for voice in ["Sulafat", "Achernar", "Charon", "Kore"]:
    ok = False
    for m in models:
        try:
            body = {"contents": [{"parts": [{"text": "Lies ganz ruhig, warm und liebevoll wie eine Gute-Nacht-"
                                              "Geschichte für kleine Kinder vor, mit kleinen Pausen: " + TEXT}]}],
                    "generationConfig": {"responseModalities": ["AUDIO"],
                                         "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
                              headers={"x-goog-api-key": key}, json=body, timeout=180)
            if r.status_code != 200:
                notes.append(f"Gemini {m}/{voice}: {r.status_code} {r.text[:150]}")
                continue
            part = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
            pcm = base64.b64decode(part["data"])
            with wave.open(str(OUT / "tmp.wav"), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(pcm)
            to_mp3(OUT / "tmp.wav", f"2_gemini_{voice}")
            ok = True
            break
        except Exception as e:  # noqa: BLE001
            notes.append(f"Gemini {m}/{voice}: {e}")
    if not ok:
        notes.append(f"Gemini {voice}: keine Probe")

# 3) Chatterbox Multilingual auf Modal (GPU)
try:
    sys.path.insert(0, str(ROOT / "anime"))
    import modal
    from modal_app import VoiceDE, app
    with modal.enable_output(), app.run():
        v = VoiceDE()
        for i, (ex, cfg) in enumerate([(0.5, 0.5), (0.7, 0.35)]):
            wav = v.speak.remote(TEXT, exaggeration=ex, cfg_weight=cfg, seed=7)
            (OUT / "tmp.wav").write_bytes(wav)
            to_mp3(OUT / "tmp.wav", f"3_chatterbox_{'ruhig' if i == 0 else 'lebhaft'}")
except Exception as e:  # noqa: BLE001
    notes.append(f"Chatterbox: {repr(e)[:300]}")

(OUT / "tmp.wav").unlink(missing_ok=True)
print("\n".join(notes) or "alles ok")
print("::notice title=Stimmproben::" + (" | ".join(notes) or "alles ok"))
