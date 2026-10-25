"""ClipWerk – eigene Stimme: Referenz aus deinen Aufnahmen bauen und Text in deiner Stimme sprechen lassen (Modal)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from engine import data_dir, run, tool

REF = data_dir() / "stimme" / "referenz.wav"


def build_reference(files: list[Path], log=print) -> Path:
    """Fügt die Aufnahmen zusammen, entfernt Stille, normalisiert und nimmt die besten ~25 s als Stimmprobe."""
    REF.parent.mkdir(parents=True, exist_ok=True)
    tmp = REF.parent / "alle.wav"
    inputs = []
    for f in files:
        inputs += ["-i", str(f)]
    n = len(files)
    fc = "".join(f"[{i}:a]aresample=24000,aformat=channel_layouts=mono[a{i}];" for i in range(n)) + \
         "".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1,highpass=f=70,lowpass=f=11000," \
         "silenceremove=stop_periods=-1:stop_duration=0.4:stop_threshold=-40dB,loudnorm=I=-18:TP=-2[o]"
    run([tool("ffmpeg"), "-y", "-loglevel", "error", *inputs, "-filter_complex", fc, "-map", "[o]", tmp])
    total = float(run([tool("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", tmp]).stdout or 0)
    start = max(0.0, min(total - 25, total * 0.15))
    run([tool("ffmpeg"), "-y", "-loglevel", "error", "-ss", f"{start:.2f}", "-t", "25", "-i", tmp, REF])
    tmp.unlink(missing_ok=True)
    log(f"Stimmprobe gespeichert ({min(25, total):.0f} s aus {total / 60:.1f} min Aufnahmen)")
    return REF


def speak(text: str, out: Path, settings: dict, language="de", liveliness=0.5, log=print) -> Path:
    if not REF.exists():
        raise RuntimeError("Noch keine Stimmprobe – bitte zuerst Aufnahmen auswählen und „Stimme anlegen“ klicken.")
    if not (settings.get("modal_token_id") and settings.get("modal_token_secret")):
        raise RuntimeError("Bitte in den Einstellungen deinen Modal-Token eintragen.")
    os.environ["MODAL_TOKEN_ID"] = settings["modal_token_id"]
    os.environ["MODAL_TOKEN_SECRET"] = settings["modal_token_secret"]
    import modal
    log("Verbinde mit deiner Stimm-KI (beim ersten Mal ~1 Minute Startzeit) …")
    Voice = modal.Cls.from_name("clipwerk-voice", "Voice")
    wav = Voice().speak.remote(text, REF.read_bytes(), language=language, exaggeration=liveliness, cfg_weight=0.5)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.wav")
    tmp.write_bytes(wav)
    if out.suffix.lower() == ".mp3":
        run([tool("ffmpeg"), "-y", "-loglevel", "error", "-i", tmp, "-b:a", "192k", out])
        tmp.unlink(missing_ok=True)
    else:
        tmp.replace(out)
    log(f"✓ Gesprochen: {out.name}")
    return out


_ = subprocess
