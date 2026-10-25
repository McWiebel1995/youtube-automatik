"""
ClipWerk – Schnitt-Engine.

Aus Handyvideos werden automatisch:
  * 2–3 Reels (9:16, 25–60 s) mit mitlaufenden Untertiteln, Hook-Text, leiser Musik, Caption + 5 Hashtags
  * eine lange, saubere Fassung (Pausen und „ähm“ raus)

Ablauf: Ton abhören (Whisper, lokal) -> Sprechstellen finden, Füllwörter/Pausen raus -> beste Momente wählen
(Gemini, optional – ohne Schlüssel einfache Auswahl) -> rendern (ffmpeg).
Alles läuft lokal; nur bei Gemini wird der *Text* (nicht das Video) an Google geschickt.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

APP = "ClipWerk"
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".3gp", ".webm"}
FILLERS = {"äh", "ähm", "öhm", "hm", "hmm", "mh", "ähh", "äähm", "eh", "ehm", "uh", "um", "uhm"}
W, H, FPS = 1080, 1920, 30
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


# ----------------------------------------------------------------------------- Pfade & Werkzeuge
def app_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def data_dir() -> Path:
    base = Path(os.environ.get("APPDATA") or Path.home() / ".config")
    d = base / APP
    d.mkdir(parents=True, exist_ok=True)
    return d


def tool(name: str) -> str:
    exe = name + (".exe" if os.name == "nt" else "")
    for cand in (app_dir() / "bin" / exe, Path(sys.executable).parent / "bin" / exe):
        if cand.exists():
            return str(cand)
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f"{name} wurde nicht gefunden – bitte ClipWerk neu installieren.")
    return found


def run(args, **kw):
    kw.setdefault("check", True)
    kw.setdefault("capture_output", True)
    kw.setdefault("stdin", subprocess.DEVNULL)          # ohne Konsole würde ffmpeg sonst auf Tastatureingaben warten
    return subprocess.run([str(a) for a in args], creationflags=CREATE_NO_WINDOW, **kw)


def font_file() -> Path | None:
    for cand in (app_dir() / "assets" / "Poppins-ExtraBold.ttf",
                 Path(__file__).resolve().parent / "assets" / "Poppins-ExtraBold.ttf"):
        if cand.exists():
            return cand
    return None


# ----------------------------------------------------------------------------- Einstellungen
DEFAULTS = {
    "gemini_key": "", "whisper_model": "small", "language": "de", "reels": 2, "reel_min": 25, "reel_max": 55,
    "music": True, "music_dir": "", "music_db": -22, "subtitles": True, "hook": True, "long_version": True,
    "style": "hof", "instagram": "", "highlight_color": "#FFD700", "projects_dir": "",
    "modal_token_id": "", "modal_token_secret": "",
}


def load_settings() -> dict:
    p = data_dir() / "settings.json"
    s = dict(DEFAULTS)
    try:
        s.update(json.loads(p.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        pass
    if not s["projects_dir"]:
        s["projects_dir"] = str(Path.home() / "Videos" / APP)
    return s


def save_settings(s: dict):
    (data_dir() / "settings.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")


# ----------------------------------------------------------------------------- Video-Infos
@dataclass
class Clip:
    path: Path
    duration: float = 0.0
    width: int = 0
    height: int = 0
    has_audio: bool = True
    words: list = field(default_factory=list)      # [(wort, start, ende)]

    @property
    def vertical(self):
        return self.height >= self.width


def probe(path: Path) -> Clip:
    out = run([tool("ffprobe"), "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path]).stdout
    js = json.loads(out)
    c = Clip(Path(path), duration=float(js.get("format", {}).get("duration", 0) or 0))
    v = next((s for s in js.get("streams", []) if s.get("codec_type") == "video"), None)
    if v:
        c.width, c.height = int(v.get("width", 0)), int(v.get("height", 0))
        rot = 0
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = int(float(sd["rotation"]))
        rot = rot or int(float((v.get("tags") or {}).get("rotate", 0) or 0))
        if abs(rot) % 180 == 90:
            c.width, c.height = c.height, c.width
    c.has_audio = any(s.get("codec_type") == "audio" for s in js.get("streams", []))
    return c


def thumbnail(path: Path, out: Path, at: float = 1.0, width: int = 320) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    run([tool("ffmpeg"), "-y", "-loglevel", "error", "-ss", f"{at:.2f}", "-i", path, "-frames:v", "1",
         "-vf", f"scale={width}:-2", out], check=False)
    return out


# ----------------------------------------------------------------------------- 1. Abhören (Whisper)
_WHISPER = {}


def transcribe(clip: Clip, cache_dir: Path, model="small", language="de", log=print) -> list:
    st = clip.path.stat()
    key = hashlib.md5(f"{clip.path}|{st.st_size}|{st.st_mtime}|{model}".encode()).hexdigest()
    cache = cache_dir / f"{key}.json"
    if cache.exists():
        return [tuple(w) for w in json.loads(cache.read_text(encoding="utf-8"))]
    if not clip.has_audio:
        return []
    cache_dir.mkdir(parents=True, exist_ok=True)
    wav = cache_dir / f"{key}.wav"
    run([tool("ffmpeg"), "-y", "-loglevel", "error", "-i", clip.path, "-vn", "-ac", "1", "-ar", "16000", wav])
    if model not in _WHISPER:
        log(f"Lade Spracherkennung ({model}) – beim ersten Mal dauert das etwas …")
        from faster_whisper import WhisperModel
        _WHISPER[model] = WhisperModel(model, device="cpu", compute_type="int8",
                                       download_root=str(data_dir() / "models"))
    segs, _ = _WHISPER[model].transcribe(str(wav), language=language or None, word_timestamps=True,
                                         vad_filter=True, beam_size=5)
    words = [(w.word.strip(), float(w.start), float(w.end)) for s in segs for w in (s.words or []) if w.word.strip()]
    cache.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    wav.unlink(missing_ok=True)
    return words


# ----------------------------------------------------------------------------- 2. Sprechstellen & B-Roll
@dataclass
class Unit:
    id: int
    clip: int
    start: float
    end: float
    text: str
    speech: bool = True

    @property
    def dur(self):
        return self.end - self.start


def _norm(w):
    return re.sub(r"[^\wäöüß]", "", w.lower())


def units_for(clips: list[Clip]) -> list[Unit]:
    """Zerlegt alle Clips in Sätze (Sprache) bzw. kurze Bildstücke (ohne Sprache). Füllwörter & Pausen fliegen raus."""
    units, uid = [], 0
    for ci, c in enumerate(clips):
        words = [w for w in c.words if _norm(w[0]) not in FILLERS]
        speech_ratio = sum(e - s for _, s, e in words) / max(1.0, c.duration)
        if len(words) >= 3 and speech_ratio > 0.15:
            cur = []
            for w in words:
                gap = w[1] - cur[-1][2] if cur else 0
                sent_end = cur and cur[-1][0][-1:] in ".!?"
                if cur and (gap > 0.7 or (sent_end and gap > 0.25) or cur[-1][2] - cur[0][1] > 12):
                    units.append(Unit(uid, ci, max(0, cur[0][1] - 0.08), min(c.duration, cur[-1][2] + 0.18),
                                      " ".join(x[0] for x in cur)))
                    uid += 1
                    cur = []
                cur.append(w)
            if cur:
                units.append(Unit(uid, ci, max(0, cur[0][1] - 0.08), min(c.duration, cur[-1][2] + 0.18),
                                  " ".join(x[0] for x in cur)))
                uid += 1
        else:                                       # B-Roll: ruhige 3-s-Stücke, gleichmäßig verteilt
            n = max(1, min(6, int(c.duration // 4)))
            for k in range(n):
                s = 0.4 + (c.duration - 3.8) * k / max(1, n - 1) if n > 1 else max(0, c.duration / 2 - 1.5)
                units.append(Unit(uid, ci, max(0, s), min(c.duration, s + 3.0), "[Bild ohne Sprache]", speech=False))
                uid += 1
    return units


# ----------------------------------------------------------------------------- 3. Auswahl (Gemini)
STYLES = {
    "hof": ("Instagram-Account über das Leben auf dem eigenen Hof: alles selbst gemacht, ehrlich, bodenständig, "
            "Vorher/Nachher, Handwerk, Tiere, Garten. Ton: authentisch, nahbar, kein Werbesprech.",
            ["#hofleben", "#selbstgemacht", "#landleben", "#diy", "#selbstversorger"]),
    "kochen": ("Instagram-Account mit Kochvideos: einfache, ehrliche Rezepte, Zutaten, Schritte, Anrichten, erster Bissen. "
               "Ton: herzlich, appetitlich, kurz erklärt.",
               ["#kochen", "#rezept", "#selbstgekocht", "#foodie", "#hausmannskost"]),
    "allgemein": ("Persönlicher Instagram-Account mit Alltagsvideos. Ton: locker und authentisch.",
                  ["#alltag", "#reels", "#authentisch", "#daily", "#leben"]),
}
SELECT_TASK = """Du bist Video-Editor für Instagram-Reels.
Account: {style}
Unten stehen die Stücke aus den Rohaufnahmen (id, Länge in Sekunden, gesprochener Text; „[Bild ohne Sprache]“ = nur Bild).
Baue {n} verschiedene Reels, jedes {rmin}–{rmax} Sekunden lang, jedes erzählt EINE kleine Geschichte:
starker Einstieg (das Spannendste/Ergebnis zuerst oder eine Frage), dann der Weg, dann ein Abschluss.
Nutze Bildstücke ohne Sprache als Zwischenschnitte. Wiederholungen/Versprecher (gleicher Satz zweimal) -> nur den besseren nehmen.
Reihenfolge der ids = Reihenfolge im Reel (darf von der Aufnahme abweichen, aber logisch bleiben).
Für jedes Reel: hook = Text für die ersten 2 Sekunden im Bild (max. 6 Wörter, neugierig machend, deutsch),
caption = Instagram-Text (2–4 Sätze, persönlich, mit 1–2 Emojis, Frage an die Community am Ende),
hashtags = genau 5 passende (Mischung aus groß und speziell), title = kurzer Dateiname.
Außerdem long = Titel + Beschreibung für die lange Fassung.
Antworte NUR mit JSON:
{{"reels":[{{"title":"...","hook":"...","caption":"...","hashtags":["#..."],"ids":[1,2,3]}}],
  "long":{{"title":"...","caption":"..."}}}}

Stücke:
{units}"""


def gemini_json(key: str, prompt: str, log=print) -> dict:
    import requests
    last = None
    for model in ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash"):
        for attempt in range(3):
            try:
                r = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    params={"key": key}, timeout=120,
                    json={"contents": [{"parts": [{"text": prompt}]}],
                          "generationConfig": {"temperature": 0.7, "responseMimeType": "application/json"}})
                if r.status_code == 404:
                    break
                if r.status_code in (429, 500, 503):
                    time.sleep(4 * (attempt + 1))
                    continue
                r.raise_for_status()
                txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(re.sub(r"^```(json)?|```$", "", txt.strip()))
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(2)
    raise RuntimeError(f"Gemini nicht erreichbar: {last}")


def select(units: list[Unit], settings: dict, log=print) -> dict:
    style, tags = STYLES.get(settings["style"], STYLES["allgemein"])
    n, rmin, rmax = int(settings["reels"]), int(settings["reel_min"]), int(settings["reel_max"])
    if settings.get("gemini_key"):
        try:
            lst = "\n".join(f"{u.id} | {u.dur:.1f}s | {u.text[:220]}" for u in units)
            js = gemini_json(settings["gemini_key"], SELECT_TASK.format(style=style, n=n, rmin=rmin, rmax=rmax,
                                                                        units=lst[:60000]), log)
            byid = {u.id: u for u in units}
            for r in js.get("reels", []):
                r["ids"] = [i for i in r.get("ids", []) if i in byid]
                tot = 0
                keep = []
                for i in r["ids"]:                  # Länge absichern
                    if tot + byid[i].dur > rmax + 5 and tot >= rmin:
                        break
                    keep.append(i)
                    tot += byid[i].dur
                r["ids"] = keep
                r["hashtags"] = (r.get("hashtags") or tags)[:5]
            js["reels"] = [r for r in js.get("reels", []) if r["ids"]][:n]
            if js["reels"]:
                return js
        except Exception as e:  # noqa: BLE001
            log(f"⚠ Automatische Auswahl nicht möglich ({e}) – nutze einfache Auswahl.")
    # Ohne Gemini: der Reihe nach aufteilen
    reels, cur, tot = [], [], 0.0
    for u in units:
        cur.append(u.id)
        tot += u.dur
        if tot >= (rmin + rmax) / 2:
            reels.append(cur)
            cur, tot = [], 0.0
        if len(reels) >= n:
            break
    if cur and len(reels) < n and tot >= rmin * 0.6:
        reels.append(cur)
    if not reels:
        reels = [[u.id for u in units]]
    return {"reels": [{"title": f"reel_{k + 1}", "hook": "", "caption": "", "hashtags": tags, "ids": ids}
                      for k, ids in enumerate(reels)],
            "long": {"title": "lange_fassung", "caption": ""}}


# ----------------------------------------------------------------------------- 4. Rendern
def _hex_to_ass(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}&".upper()


def karaoke_ass(words, path: Path, w, h, hook="", hook_until=2.6, color="#FFD700", subtitles=True):
    fnt = "Poppins ExtraBold" if font_file() else "Arial"
    size = int(w * 0.075)
    hi = _hex_to_ass(color)

    def ts(x):
        hh, r = divmod(max(0, x), 3600)
        mm, ss = divmod(r, 60)
        return f"{int(hh)}:{int(mm):02d}:{ss:05.2f}"
    head = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {w}\nPlayResY: {h}\nWrapStyle: 2\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
            "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
            "MarginR, MarginV, Encoding\n"
            f"Style: K,{fnt},{size},&H00FFFFFF,&H000000FF,&H00000000,&H96000000,0,0,0,0,100,100,1,0,1,"
            f"{max(3, size // 14)},{max(2, size // 22)},2,60,60,{int(h * 0.22)},1\n"
            f"Style: Hook,{fnt},{int(size * 1.05)},&H00FFFFFF,&H000000FF,&H00000000,&HB4000000,0,0,0,0,100,100,1,0,3,"
            f"18,0,8,70,70,{int(h * 0.12)},1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    ev = []
    if hook:
        ev.append(f"Dialogue: 1,{ts(0)},{ts(hook_until)},Hook,,0,0,0,,{{\\fad(120,250)}}{hook.upper()}")
    if subtitles and words:
        groups, cur = [], []
        for wd in words:
            if cur and (len(cur) >= 3 or cur[-1][0][-1:] in ".,!?;:" or wd[1] - cur[-1][2] > 0.6):
                groups.append(cur)
                cur = []
            cur.append(wd)
        groups += [cur] if cur else []
        for gi, g in enumerate(groups):
            end = min(g[-1][2] + 0.35, groups[gi + 1][0][1]) if gi + 1 < len(groups) else g[-1][2] + 0.5
            for k, (_, a, _) in enumerate(g):
                b2 = g[k + 1][1] if k + 1 < len(g) else end
                parts = []
                for j, (x, _, _) in enumerate(g):
                    x = x.replace("{", "(").replace("}", ")").upper()
                    parts.append(f"{{\\c{hi}\\fscx110\\fscy110}}{x}{{\\c&HFFFFFF&\\fscx100\\fscy100}}" if j == k else x)
                ev.append(f"Dialogue: 0,{ts(a)},{ts(b2)},K,,0,0,0,,{' '.join(parts)}")
    path.write_text(head + "\n".join(ev) + "\n", encoding="utf-8")


def _segment(clip: Clip, u: Unit, out: Path, w=W, h=H):
    if clip.vertical == (h >= w):
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps={FPS},format=yuv420p"
        fc = None
    else:                                           # Querformat in Hochformat: unscharfer Hintergrund + Bild in der Mitte
        fc = (f"[0:v]split[a][b];[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=30:3[bg];"
              f"[b]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,"
              f"setsar=1,fps={FPS},format=yuv420p[v]")
    args = [tool("ffmpeg"), "-y", "-loglevel", "error", "-ss", f"{u.start:.3f}", "-to", f"{u.end:.3f}", "-i", clip.path]
    if not clip.has_audio:
        args += ["-f", "lavfi", "-t", f"{u.dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
    if fc:
        args += ["-filter_complex", fc, "-map", "[v]"]
    else:
        args += ["-vf", vf, "-map", "0:v:0"]
    args += ["-map", "0:a:0" if clip.has_audio else "1:a:0", "-af", "aresample=48000,afade=t=in:d=0.04,"
             f"afade=t=out:st={max(0, u.dur - 0.06):.3f}:d=0.06", "-ac", "2",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k", "-shortest", out]
    run(args)


def _music(settings) -> Path | None:
    d = Path(settings.get("music_dir") or "")
    files = [p for p in d.glob("*") if p.suffix.lower() in {".mp3", ".wav", ".m4a", ".ogg"}] if d.is_dir() else []
    return random.choice(files) if files else None


def render(clips, units_sel: list[Unit], out: Path, work: Path, settings: dict, hook="", vertical=True, log=print):
    w, h = (W, H) if vertical else (H, W)
    work.mkdir(parents=True, exist_ok=True)
    parts, words, t = [], [], 0.0
    for k, u in enumerate(units_sel):
        p = work / f"seg_{k:03d}.mp4"
        _segment(clips[u.clip], u, p, w, h)
        parts.append(p)
        for (x, a, b) in clips[u.clip].words:
            if a >= u.start - 0.02 and b <= u.end + 0.05 and _norm(x) not in FILLERS:
                words.append((x, t + a - u.start, t + b - u.start))
        t += u.dur
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    joined = work / "joined.mp4"
    run([tool("ffmpeg"), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", joined])
    ass = work / "subs.ass"
    karaoke_ass(words, ass, w, h, hook if settings.get("hook", True) else "",
                color=settings.get("highlight_color", "#FFD700"), subtitles=settings.get("subtitles", True))
    if font_file():                                  # Schrift in den Arbeitsordner -> keine Windows-Pfadprobleme
        (work / "fonts").mkdir(exist_ok=True)
        shutil.copy(font_file(), work / "fonts" / font_file().name)
    vf = "[0:v]subtitles=subs.ass" + (":fontsdir=fonts" if font_file() else "") + "[v]"
    music = _music(settings) if settings.get("music", True) else None
    args = [tool("ffmpeg"), "-y", "-loglevel", "error", "-i", joined.name]
    if music:
        args += ["-stream_loop", "-1", "-i", str(music)]
        db = float(settings.get("music_db", -22))
        fa = (f"[1:a]volume={db}dB,aformat=channel_layouts=stereo[m];[m][0:a]sidechaincompress=threshold=0.03:"
              f"ratio=6:attack=20:release=400[md];[0:a][md]amix=inputs=2:duration=first:normalize=0,"
              f"loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    else:
        fa = "[0:a]loudnorm=I=-14:TP=-1.5:LRA=11[a]"
    args += ["-filter_complex", vf + ";" + fa, "-map", "[v]", "-map", "[a]",
             "-t", f"{t:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out.resolve())]
    run(args, cwd=work)
    return t


# ----------------------------------------------------------------------------- Gesamtablauf
def process(paths: list[Path], out_dir: Path, settings: dict, progress=lambda p, m: None, log=print) -> dict:
    """Hauptfunktion: Videos rein, fertige Reels + lange Fassung raus. Gibt eine Übersicht (dict) zurück."""
    paths = [Path(p) for p in paths if Path(p).suffix.lower() in VIDEO_EXT]
    if not paths:
        raise RuntimeError("Keine Videos gefunden.")
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = data_dir() / "cache"
    work = Path(tempfile.mkdtemp(prefix="clipwerk_"))
    try:
        progress(2, "Videos prüfen …")
        clips = [probe(p) for p in paths]
        for i, c in enumerate(clips):
            progress(5 + 40 * i / len(clips), f"Höre zu: {c.path.name} ({i + 1}/{len(clips)})")
            c.words = transcribe(c, cache, settings.get("whisper_model", "small"), settings.get("language", "de"), log)
            log(f"  {c.path.name}: {c.duration:.0f} s, {len(c.words)} Wörter")
        progress(46, "Pausen und Füllwörter entfernen …")
        units = units_for(clips)
        if not units:
            raise RuntimeError("In den Videos wurde nichts Verwertbares gefunden.")
        progress(50, "Beste Momente auswählen …")
        plan = select(units, settings, log)
        byid = {u.id: u for u in units}
        vertical = sum(c.vertical for c in clips) >= len(clips) / 2
        results = {"reels": [], "long": None, "created": time.strftime("%Y-%m-%d %H:%M")}
        n = len(plan["reels"]) + (1 if settings.get("long_version", True) else 0)
        for k, r in enumerate(plan["reels"]):
            progress(55 + 40 * k / n, f"Reel {k + 1}/{len(plan['reels'])} schneiden …")
            name = re.sub(r"[^\w\-äöüÄÖÜß]+", "_", r.get("title") or f"reel_{k + 1}").strip("_")[:40] or f"reel_{k + 1}"
            mp4 = out_dir / f"{k + 1:02d}_{name}.mp4"
            dur = render(clips, [byid[i] for i in r["ids"]], mp4, work / f"r{k}", settings, r.get("hook", ""), True, log)
            caption = (r.get("caption", "").strip() + "\n\n" + " ".join(r.get("hashtags", [])[:5])).strip()
            mp4.with_suffix(".txt").write_text(caption, encoding="utf-8")
            thumbnail(mp4, mp4.with_suffix(".jpg"), at=min(1.5, dur / 3), width=360)
            results["reels"].append({"file": mp4.name, "duration": round(dur, 1), "hook": r.get("hook", ""),
                                     "caption": caption, "thumb": mp4.with_suffix(".jpg").name})
            log(f"✓ {mp4.name} ({dur:.0f} s)")
        if settings.get("long_version", True):
            progress(55 + 40 * (n - 1) / n, "Lange Fassung schneiden …")
            mp4 = out_dir / "00_lange_fassung.mp4"
            sp = [u for u in units if u.speech] or units
            dur = render(clips, sp, mp4, work / "long", dict(settings, music=False), "", vertical, log)
            thumbnail(mp4, mp4.with_suffix(".jpg"), at=min(2, dur / 3), width=360)
            cap = (plan.get("long") or {}).get("caption", "")
            mp4.with_suffix(".txt").write_text(cap, encoding="utf-8")
            results["long"] = {"file": mp4.name, "duration": round(dur, 1), "caption": cap, "thumb": mp4.with_suffix(".jpg").name}
            log(f"✓ Lange Fassung ({dur / 60:.1f} min, vorher {sum(c.duration for c in clips) / 60:.1f} min)")
        (out_dir / "ergebnis.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        progress(100, "Fertig!")
        return results
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":                          # Kommandozeile / Selbsttest: python engine.py video1.mp4 ... --out ordner
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("videos", nargs="+")
    ap.add_argument("--out", default="ClipWerk_Ergebnis")
    ap.add_argument("--model", default=None)
    a = ap.parse_args()
    s = load_settings()
    if a.model:
        s["whisper_model"] = a.model
    res = process([Path(v) for v in a.videos], Path(a.out), s,
                  progress=lambda p, m: print(f"[{p:5.1f}%] {m}", flush=True))
    print(json.dumps(res, ensure_ascii=False, indent=1))
