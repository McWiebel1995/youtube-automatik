"""40-Sekunden-Hochkant-Clip aus einem Relax-Video für Instagram (@calmhavenig)."""
import subprocess
from pathlib import Path

from common import duration

ROOT = Path(__file__).resolve().parent.parent
LABEL = {"regen": "rain", "kamin": "fireplace", "wasserfall": "waterfall"}
HEAD = {
    "regen": ["{h} hours of rain to fall asleep to", "Rain on the window. Phone down. {h} hours.", "The rain sound you need tonight"],
    "kamin": ["{h} hours by a crackling fire", "Cozy fireplace sounds for deep sleep", "Fire crackling. Tea. {h} hours of calm."],
    "wasserfall": ["{h} hours of waterfall sounds", "Let the water wash the stress away", "Falling water for deep focus"],
}
TAGS = {
    "regen": "#rainsounds #sleepsounds #rain #ambience #relaxingsounds #asmrsleep #studyambience #cozyvibes",
    "kamin": "#fireplace #cracklingfire #cozy #sleepsounds #ambience #relaxingsounds #hygge #cozyvibes",
    "wasserfall": "#waterfall #naturesounds #whitenoise #sleepsounds #relaxingsounds #meditation #focusmusic #calm",
}


def _esc(t):
    return t.replace("\\", "").replace(":", "\\:").replace("'", "’").replace("%", "")


def make(video, out: Path, hours, scene, channel, rnd, seconds=40):
    total = duration(video)
    start = rnd.uniform(60, max(61, total - seconds - 60))
    h = f"{hours:g}"
    head = rnd.choice(HEAD[channel]).format(h=h)
    font = ROOT / "assets/fonts/PlayfairDisplay.ttf"
    ff = f"fontfile={font}:" if font.exists() else ""
    (out.parent / "ig_head.txt").write_text(head, encoding="utf-8")
    vf = ("crop=ih*9/16:ih,scale=1080:1920:flags=lanczos,"
          f"drawtext={ff}textfile={out.parent / 'ig_head.txt'}:fontsize=62:fontcolor=white:"
          "x=(w-tw)/2:y=260:shadowcolor=black@0.6:shadowx=3:shadowy=3,"
          f"drawtext={ff}text='{_esc('Full ' + h + '-hour version on YouTube')}':fontsize=40:fontcolor=white@0.9:"
          "x=(w-tw)/2:y=h-300:shadowcolor=black@0.6:shadowx=2:shadowy=2,"
          f"fade=t=in:d=1,fade=t=out:st={seconds - 1.5}:d=1.5,format=yuv420p")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.1f}", "-i", str(video), "-t", str(seconds),
                    "-vf", vf, "-af", f"afade=t=in:d=1,afade=t=out:st={seconds - 2}:d=2,loudnorm=I=-16:TP=-1.5",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
                    "-movflags", "+faststart", str(out)], check=True)
    return out


def caption(channel, hours, scene, rnd):
    h = f"{hours:g}"
    lines = {
        "regen": f"Close your eyes. Just the rain. 🌧️\n{scene.capitalize()} – {h} hours of calm for sleep, study or a quiet evening.",
        "kamin": f"Crackling fire, warm light, nowhere to be. 🔥\n{scene.capitalize()} – {h} hours of cozy fireplace sounds.",
        "wasserfall": f"Let the water carry your thoughts away. 🌊\n{scene.capitalize()} – {h} hours of natural water sounds.",
    }[channel]
    return (f"{lines}\n\n💾 Save this for tonight\n▶️ Full {h}-hour version on YouTube (link in bio)\n\n{TAGS[channel]}")
