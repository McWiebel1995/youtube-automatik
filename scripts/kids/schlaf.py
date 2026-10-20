"""Schlafkanal: neue Spieluhr-Schlaflieder + Sternenhimmel-Loop, 1–3 Stunden."""
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import ASSETS, ffmpeg  # noqa: E402

import music  # noqa: E402
import visuals  # noqa: E402

FPS = 24


def write_wav(path, data, sr=44100):
    wavfile.write(str(path), sr, (np.clip(data, -1, 1) * 32767).astype(np.int16))


def render_loop(scene_fn, seed, seconds, out, size=(1920, 1080)):
    """Rendert eine Szene als nahtlosen Loop (intern 960x540, weich hochskaliert)."""
    rng = np.random.default_rng(seed)
    make = scene_fn(rng, float(seconds))
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{visuals.W}x{visuals.H}", "-r", str(FPS), "-i", "-",
           "-vf", f"scale={size[0]}:{size[1]}:flags=lanczos:force_original_aspect_ratio=increase,"
                  f"crop={size[0]}:{size[1]}",
           "-c:v", "libx264", "-profile:v", "high", "-level", "4.1", "-preset", "slow", "-crf", "22", "-pix_fmt", "yuv420p",
           "-g", str(FPS * 2), "-movflags", "+faststart", "-f", "mp4", str(out) + ".part"]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(int(seconds * FPS)):
        p.stdin.write(np.clip(make(i / FPS), 0, 255).astype(np.uint8).tobytes())
    p.stdin.close()
    if p.wait():
        raise RuntimeError("ffmpeg-Fehler beim Rendern der Szene")
    Path(str(out) + ".part").replace(out)


def ensure_loops(variants=4, seconds=20):
    out_dir = ASSETS / "schlaf" / "video"
    out_dir.mkdir(parents=True, exist_ok=True)
    for v in range(1, variants + 1):
        out = out_dir / f"sky_{v:02d}.mp4"
        if not out.exists():
            render_loop(visuals.nachthimmel, 500 + v, seconds, out)
            print(f"  ✓ {out.relative_to(ASSETS.parent)}")
    return sorted(out_dir.glob("*.mp4"))


def produce(ch, seconds, work: Path, rnd):
    work.mkdir(parents=True, exist_ok=True)
    loops = ensure_loops()
    loop = rnd.choice(loops)

    # 1) 6–8 neue Schlaflieder komponieren (~25 Minuten Musik), danach wird geloopt
    pieces = []
    total = 0
    count = rnd.randint(6, 8)
    for _ in range(count):
        y = music.lullaby(rnd.randrange(2**31))
        pieces.append(y)
        pieces.append(np.zeros((int(2.5 * 44100), 2)))
        total += len(y)
        if total / 44100 >= seconds:
            break
    block = np.concatenate(pieces)
    block_wav = work / "music.wav"
    write_wav(block_wav, block)

    with_noise = rnd.random() < ch.get("with_noise_chance", 0.5)
    fade = 10
    chain = (f"[0:a]atrim=0:{seconds},asetpts=N/SR/TB[m];")
    inputs = ["-stream_loop", "-1", "-i", block_wav]
    if with_noise:
        inputs += ["-f", "lavfi", "-i", f"anoisesrc=color=pink:amplitude=0.5:seed={rnd.randrange(9999)}"]
        chain += (f"[1:a]lowpass=f=1800,volume=-26dB,atrim=0:{seconds},aformat=channel_layouts=stereo[n];"
                  f"[m][n]amix=inputs=2:normalize=0,")
    else:
        chain += "[m]"
    chain += (f"afade=t=in:d={fade},afade=t=out:st={seconds - fade}:d={fade},"
              f"loudnorm=I=-23:TP=-2:LRA=11,aresample=44100[out]")
    audio = work / "audio.m4a"
    ffmpeg(*inputs, "-filter_complex", chain, "-map", "[out]", "-t", seconds,
           "-c:a", "aac", "-b:a", "192k", audio)

    out = work / "video.mp4"
    from render import concat_loop
    concat_loop(loop, audio, seconds, out, work)
    block_wav.unlink(missing_ok=True)
    audio.unlink(missing_ok=True)
    return {"video_file": str(out), "loop": str(loop), "with_noise": with_noise, "songs": count}


def metadata(ch, info, minutes, rnd):
    theme = rnd.choice(ch["themes"])
    noise = " + sanftes Rauschen" if info["with_noise"] else ""
    title = rnd.choice(ch["title_templates"]).format(theme=theme, noise=noise)[:100]
    desc = "\n".join([
        f"Sanfte Spieluhr-Musik {theme}{noise} – genau richtig für die Einschlafphase.",
        "",
        "Ruhige Schlaflieder helfen deinem Baby beim Einschlafen.",
        "Der Bildschirm bleibt dunkel und ruhig – du kannst ihn auch einfach ausschalten",
        "oder das Handy weglegen und nur die Musik laufen lassen.",
        "",
        "🎵 Alle Melodien sind eigene Kompositionen und für diesen Kanal erstellt.",
        "",
        "💤 Tipp: Leise abspielen und das Gerät nicht direkt neben das Babybett legen.",
        "",
        "#Einschlafmusik #Spieluhr #Babyschlaf",
    ])
    return {"title": title, "description": desc, "tags": ch["tags"], "scene": theme,
            "thumb_label": "15 MIN", "thumb_sub": "SPIELUHR ZUM EINSCHLAFEN"}


def short_metadata(ch, info, rnd):
    title = rnd.choice(ch["short_titles"]).format(greeting=info["title_word"])[:100]
    desc = "\n".join([
        f"{info['title_word']} – {info['subtitle']}. 🌙",
        "Ein neues Spieluhr-Schlaflied, jeden Tag.",
        "",
        "Die ganze Einschlafmusik findest du auf dem Kanal.",
        "",
        "#shorts #Einschlafmusik #Spieluhr #Schlaflied",
    ])
    return {"title": title, "description": desc, "tags": ch["tags"] + ["shorts"]}
