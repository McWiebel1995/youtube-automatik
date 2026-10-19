"""Mischt Sound-Ebenen zufällig und legt sie unter einen Video-Loop."""
import json
import random
from pathlib import Path

from common import ASSETS, duration, ffmpeg


def pick_layers(channel, rnd):
    """Wählt Basis-Sound + zufällige Extras mit zufälliger Lautstärke."""
    audio_dir = ASSETS / channel["key"] / "audio"
    layers = []

    def choose(spec):
        files = sorted(audio_dir.glob(spec["pattern"] + ".flac")) + sorted(audio_dir.glob(spec["pattern"] + ".wav"))
        if not files:
            return None
        real = [f for f in files if f.stem.split("_", 1)[-1].startswith("fs")]   # echte Aufnahmen
        synth = [f for f in files if f not in real]
        pool = real if real and (not synth or rnd.random() < 0.9) else synth
        lo, hi = spec["gain_db"]
        return {"file": rnd.choice(pool), "gain_db": round(rnd.uniform(lo, hi), 1),
                "prefix": spec["pattern"].rstrip("*")}

    base = choose(channel["layers"]["base"])
    if base is None:
        raise SystemExit(f"Keine Basis-Sounds in {audio_dir} – zuerst gen_audio.py ausführen.")
    layers.append(base)
    for spec in channel["layers"].get("extras", []):
        if rnd.random() < spec.get("chance", 0.5):
            layer = choose(spec)
            if layer:
                layers.append(layer)
    return layers


def pick_video(channel, rnd, real_share=0.9):
    """Echte Clips (Pixabay/Pexels) werden bevorzugt, gezeichnete Szenen nur selten."""
    files = sorted((ASSETS / channel["key"] / "video").glob("*.mp4"))
    if not files:
        raise SystemExit(f"Keine Video-Loops für {channel['key']} – zuerst gen_video.py ausführen.")
    real = [f for f in files if f.name.startswith(("pixabay_", "pexels_"))]
    drawn = [f for f in files if f not in real]
    if real and (not drawn or rnd.random() < real_share):
        return rnd.choice(real)
    return rnd.choice(drawn)


def render(channel, seconds, workdir: Path, rnd: random.Random):
    workdir.mkdir(parents=True, exist_ok=True)
    layers = pick_layers(channel, rnd)
    video = pick_video(channel, rnd)
    fade = channel.get("fade_seconds", 8)

    # 1) Audio mischen (jede Ebene endlos geloopt, dann auf Länge geschnitten)
    args = []
    for layer in layers:
        args += ["-stream_loop", "-1", "-i", layer["file"]]
    chains = [f"[{i}:a]aresample=44100,volume={l['gain_db']}dB[a{i}]" for i, l in enumerate(layers)]
    mix_in = "".join(f"[a{i}]" for i in range(len(layers)))
    chains.append(
        f"{mix_in}amix=inputs={len(layers)}:normalize=0:duration=longest,"
        f"atrim=0:{seconds},afade=t=in:d={fade},afade=t=out:st={seconds - fade}:d={fade},"
        f"loudnorm=I=-20:TP=-1.5:LRA=11,aresample=44100[out]"
    )
    audio = workdir / "audio.m4a"
    ffmpeg(*args, "-filter_complex", ";".join(chains), "-map", "[out]",
           "-t", seconds, "-c:a", "aac", "-b:a", "192k", audio)

    # 2) Video-Loop ohne Neukodierung wiederholen und Ton dazulegen
    out = workdir / "video.mp4"
    concat_loop(video, audio, seconds, out, workdir)

    scene = None
    side = video.with_suffix(".json")
    if side.exists():
        scene = json.loads(side.read_text(encoding="utf-8")).get("scene")
    return {
        "video_file": str(out),
        "loop": video.name,
        "loop_scene": scene,
        "layers": [{"file": Path(l["file"]).name, "gain_db": l["gain_db"], "prefix": l["prefix"]}
                   for l in layers],
    }


def concat_loop(video, audio, seconds, out, workdir):
    """Wiederholt den Loop per concat-Liste (saubere Zeitstempel, läuft in allen Playern)."""
    import math
    reps = math.ceil(seconds / max(duration(video), 1)) + 1
    lst = Path(workdir) / "loop.txt"
    lst.write_text("".join(f"file '{Path(video).resolve().as_posix()}'\n" for _ in range(reps)))
    ffmpeg("-f", "concat", "-safe", "0", "-i", lst, "-i", audio,
           "-map", "0:v", "-map", "1:a", "-c", "copy", "-t", seconds,
           "-tag:v", "avc1", "-movflags", "+faststart", out)
    lst.unlink(missing_ok=True)
