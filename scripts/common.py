"""Gemeinsame Helfer: Konfiguration laden, Pfade, ffmpeg-Aufrufe."""
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
OUTPUT = ROOT / "output"
CONFIG = ROOT / "config" / "channels.yaml"


def load_config():
    with open(CONFIG, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    defaults = cfg.get("defaults", {})
    for key, ch in cfg["channels"].items():
        ch["key"] = key
        for k, v in defaults.items():
            ch.setdefault(k, v)
    return cfg


def ffmpeg(*args):
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *map(str, args)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg fehlgeschlagen:\n{' '.join(cmd)}\n{res.stderr}")


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())
