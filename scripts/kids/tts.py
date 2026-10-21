"""
Deutsche Sprachausgabe.

Standard (TTS_ENGINE=chatterbox): Chatterbox Multilingual auf Modal-GPU mit deutscher Referenzstimme
(data/voices/ref_sulafat.wav, eine Gemini-„Sulafat“-Probe) -> natürlich, ohne Akzent, ohne Tageslimit.
Ersatz: Piper (offline, kostenlos).
Stimmen werden beim ersten Lauf automatisch heruntergeladen (rhasspy/piper-voices).

Fallbacks, falls Piper fehlt (z. B. lokal zum Testen):
  1. espeak-ng (klingt robotisch, nur zum Testen)
  2. Stille mit passender Länge (damit die Pipeline trotzdem durchläuft)
"""
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
VOICE_DIR = ROOT / "assets" / "voices"
HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
SR = 22050

_voice_cache = {}
_warned = set()


def _warn(msg):
    if msg not in _warned:
        print(f"  ⚠ {msg}")
        _warned.add(msg)


def ensure_voice(name):
    """Lädt z. B. 'de_DE-thorsten-medium' (.onnx + .onnx.json), falls nicht vorhanden."""
    lang, speaker, quality = name.split("-")
    model = VOICE_DIR / f"{name}.onnx"
    if model.exists() and model.with_suffix(".onnx.json").exists():
        return model
    import requests

    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    base = f"{HF}/{lang.split('_')[0]}/{lang}/{speaker}/{quality}/{name}"
    for suffix in (".onnx", ".onnx.json"):
        r = requests.get(base + suffix, timeout=300)
        r.raise_for_status()
        (VOICE_DIR / f"{name}{suffix}").write_bytes(r.content)
    return model


def _piper(text, out, voice, rate):
    from piper import PiperVoice  # noqa: WPS433

    if voice not in _voice_cache:
        _voice_cache[voice] = PiperVoice.load(str(ensure_voice(voice)))
    v = _voice_cache[voice]
    with wave.open(str(out), "wb") as wf:
        try:  # piper-tts >= 1.3
            from piper import SynthesisConfig
            v.synthesize_wav(text, wf, syn_config=SynthesisConfig(length_scale=1 / rate))
        except ImportError:  # piper-tts 1.2
            v.synthesize(text, wf, length_scale=1 / rate)


def _espeak(text, out, rate):
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    if not exe:
        raise FileNotFoundError
    subprocess.run([exe, "-v", "de", "-s", str(int(150 * rate)), "-w", str(out), text], check=True)


def _silence(text, out):
    secs = max(0.8, 0.38 * len(text.split()))
    with wave.open(str(out), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(np.zeros(int(secs * SR), np.int16).tobytes())


# ----------------------------------------------------------------- Chatterbox (Modal-GPU)
import os  # noqa: E402

_cb = {}
STYLE = {"ruhig": (0.5, 0.0), "lebhaft": (0.75, 0.0)}


def _chatterbox(text, out, style="ruhig"):
    if "voice" not in _cb:
        import atexit
        import sys
        sys.path.insert(0, str(ROOT / "anime"))
        import modal
        from modal_app import VoiceDE, app
        ctx = app.run()
        ctx.__enter__()
        atexit.register(lambda: ctx.__exit__(None, None, None))
        _cb["voice"] = VoiceDE()
        ref = Path(os.environ.get("TTS_REF", ROOT / "data" / "voices" / "ref_sulafat.wav"))
        _cb["ref"] = ref.read_bytes() if ref.exists() else b""
        _cb["n"] = 0
        _ = modal
    ex, cfg = STYLE.get(style, STYLE["ruhig"])
    wav = _cb["voice"].speak.remote(text, ref_wav=_cb["ref"], exaggeration=ex, cfg_weight=cfg, seed=11)
    Path(out).write_bytes(wav)
    _cb["n"] += 1


def engine():
    return os.environ.get("TTS_ENGINE", "piper")


def speak(text, out, voice="de_DE-thorsten-medium", rate=0.92, style=None):
    """Schreibt die gesprochene Zeile als WAV und gibt die Dauer in Sekunden zurück."""
    out = Path(out)
    if engine() == "chatterbox" and not _cb.get("failed"):
        try:
            _chatterbox(text, out, style or os.environ.get("TTS_STYLE", "ruhig"))
            with wave.open(str(out)) as wf:
                return wf.getnframes() / wf.getframerate()
        except Exception as e:  # noqa: BLE001
            _cb["failed"] = True
            _warn(f"Chatterbox nicht verfügbar ({repr(e)[:160]}) – nutze Piper")
            print(f"::warning title=Stimme::Chatterbox nicht verfügbar, Ersatzstimme Piper: {repr(e)[:300]}")
    try:
        _piper(text, out, voice, rate)
    except ImportError:
        try:
            _espeak(text, out, rate)
            _warn("Piper nicht installiert – nutze espeak (nur zum Testen).")
        except (FileNotFoundError, subprocess.CalledProcessError):
            _silence(text, out)
            _warn("Keine Sprachausgabe gefunden – Platzhalter-Stille (nur zum Testen).")
    with wave.open(str(out)) as wf:
        return wf.getnframes() / wf.getframerate()
