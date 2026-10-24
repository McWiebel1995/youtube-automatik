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
import os
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


_WH = {}


ZAHL = ["null", "eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun", "zehn", "elf", "zwölf",
        "dreizehn", "vierzehn", "fünfzehn", "sechzehn", "siebzehn", "achtzehn", "neunzehn", "zwanzig"]


def _norm_words(t):
    import re
    ws = re.findall(r"[a-zäöüß0-9]+", t.lower())
    return [ZAHL[int(w)] if w.isdigit() and int(w) <= 20 else ("eins" if w == "ein" else w) for w in ws]


def _heard(audio16):
    """Was die Stimme wirklich gesagt hat (Whisper, deutsch). None, wenn Whisper fehlt."""
    if _WH.get("off"):
        return None
    try:
        if "m" not in _WH:
            from faster_whisper import WhisperModel
            _WH["m"] = WhisperModel(os.environ.get("TTS_CHECK_MODEL", "small"), device="cpu", compute_type="int8")
        segs, _ = _WH["m"].transcribe(audio16, language="de", beam_size=1, vad_filter=False)
        return " ".join(s.text for s in segs)
    except Exception as e:  # noqa: BLE001
        _WH["off"] = True
        _warn(f"Sprach-Kontrolle ohne Whisper ({repr(e)[:120]})")
        return None


def _score(text, heard):
    import difflib
    a, b = " ".join(_norm_words(text)), " ".join(_norm_words(heard or ""))
    if not a:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()   # buchstabenweise: verzeiht kleine Hörfehler


def _clean(wav_bytes, text):
    """Ränder abschneiden; Nachplappern hinter dem erwarteten Ende entfernen. -> (audio float32, sr, zu_lang?)"""
    import io
    from scipy.io import wavfile as wf_
    sr, a = wf_.read(io.BytesIO(wav_bytes))
    a = a.astype(np.float32) / (32768 if a.dtype == np.int16 else 1)
    if a.ndim > 1:
        a = a.mean(axis=1)
    win = int(sr * 0.02)
    env = np.sqrt(np.convolve(a ** 2, np.ones(win) / win, "same"))
    voiced = np.where(env > max(0.006, env.max() * 0.06))[0]
    if len(voiced):
        a = a[max(0, voiced[0] - int(sr * .05)): voiced[-1] + int(sr * .12)]
        env = env[max(0, voiced[0] - int(sr * .05)): voiced[-1] + int(sr * .12)]
    words = max(1, len(_norm_words(text)))
    expect = 0.45 * words + 0.5                      # ruhiges Kindertempo
    limit = expect * 1.9 + 0.6
    too_long = len(a) / sr > limit
    if too_long:                                     # an der ersten längeren Pause nach dem erwarteten Ende schneiden
        quiet = env < max(0.006, env.max() * 0.06)
        start = int(sr * expect * 0.8)
        run, cut = 0, None
        for i in range(start, len(quiet)):
            run = run + 1 if quiet[i] else 0
            if run > sr * 0.25:
                cut = i - run + int(sr * .12)
                break
        a = a[: cut or int(sr * limit)]
        f = int(sr * 0.06)
        a[-f:] *= np.linspace(1, 0, f)
    return a, sr, too_long


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
    from scipy.io import wavfile as wf_
    from scipy.signal import resample_poly
    ex, cfg = STYLE.get(style, STYLE["ruhig"])
    best = None
    for k, seed in enumerate((11, 23, 37)):          # bis zu 3 Versuche, der beste gewinnt
        wav = _cb["voice"].speak.remote(text, ref_wav=_cb["ref"], exaggeration=ex, cfg_weight=cfg, seed=seed)
        a, sr, too_long = _clean(wav, text)
        heard = _heard(resample_poly(a, 16000, sr).astype(np.float32))
        sc = _score(text, heard) if heard is not None else (0.5 if too_long else 1.0)
        sc -= 0.3 if too_long else 0
        if best is None or sc > best[0]:
            best = (sc, a, sr, heard)
        if sc >= 0.72:
            break
        print(f"  ↻ Stimme neu (Versuch {k + 2}): „{text[:50]}“ → gehört: „{(heard or '')[:60]}“", flush=True)
    sc, a, sr, heard = best
    if sc < 0.5:
        print(f"::warning title=Stimme::Abschnitt unsicher: „{text[:60]}“ → „{(heard or '')[:60]}“")
    wf_.write(str(out), sr, (np.clip(a, -1, 1) * 32767).astype(np.int16))
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
