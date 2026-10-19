#!/usr/bin/env python3
"""
KI 3 – ANIME PRODUCTION

Für jedes freigegebene Drehbuch (anime/data/scripts/ID.json, status "approved"):
  1 BILDER     Schlüsselbild pro Shot (Modal-GPU, Animagine XL 4.0)
  2 ANIMATION  jedes Bild -> 5-s-Clip (Modal-GPU, Wan 2.2)
  3 STIMMEN    Dialog + Voice-over auf Englisch (Kokoro TTS, läuft ohne GPU)
  4 SOUND      Geräusche + Musik: echte CC0-Aufnahmen von Freesound
  5 SCHNITT    1080x1920, Untertitel, Endtafel, Lautheit für Shorts
  6 ABLAGE     als GitHub-Release (öffentlicher Link) + Status fürs Dashboard

    python anime/produce.py                 # alle freigegebenen, noch nicht produzierten
    python anime/produce.py --id VIDEOID    # nur eins
    python anime/produce.py --id VIDEOID --no-gpu   # Test ohne Modal (Platzhalter-Bilder)

Umgebung: MODAL_TOKEN_ID, MODAL_TOKEN_SECRET, FREESOUND_API_KEY, GH_TOKEN, GITHUB_REPOSITORY
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path

import numpy as np
import requests
from scipy.io import wavfile
from scipy.signal import resample_poly

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
DATA = HERE / "data"
SCRIPTS = DATA / "scripts"
PROD = DATA / "production"
WORK = HERE.parent / "output" / "anime"
SR = 48000
W, H, FPS = 1080, 1920, 30
END_CARD = "Fictional story inspired by real events."
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sh(*cmd):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"{' '.join(map(str, cmd))[:300]}\n{r.stderr[-1500:]}")
    return r.stdout


def status(vid, **kw):
    PROD.mkdir(parents=True, exist_ok=True)
    f = PROD / f"{vid}.json"
    rec = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"video_id": vid}
    rec.update(kw, updated_at=now())
    f.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    build_index()
    return rec


def build_index():
    items = []
    for f in sorted(PROD.glob("*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        items.append({k: r.get(k) for k in ["video_id", "title", "state", "progress", "video_url", "poster_url",
                                             "duration_s", "gpu_seconds", "notes", "error", "updated_at",
                                             "decision", "decided_at", "youtube"]})
    items.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
    (DATA / "productions.json").write_text(json.dumps({"updated_at": now(), "productions": items},
                                                      ensure_ascii=False, indent=1), encoding="utf-8")


# ----------------------------------------------------------------- 1+2 GPU (Modal)
def gpu_shots(vid, sc, work, no_gpu=False):
    shots = sc["shots"]
    style = (sc.get("setting") or {}).get("art_style", "cinematic anime")
    base = int(hashlib.sha1(vid.encode()).hexdigest()[:8], 16)
    notes, t0 = [], time.time()
    if no_gpu:                                   # Test ohne GPU: farbige Platzhalter-Clips
        for s in shots:
            out = work / f"clip_{s['n']:02d}.mp4"
            sh("ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
               f"color=c=0x{(s['n'] * 2654435761) % 0xFFFFFF:06x}:s=704x1280:d=5:r=24",
               "-vf", f"drawtext=fontfile={FONT}:text='Shot {s['n']}':fontsize=60:fontcolor=white:x=(w-tw)/2:y=(h-th)/2",
               "-pix_fmt", "yuv420p", out)
            sh("ffmpeg", "-y", "-loglevel", "error", "-i", out, "-frames:v", "1", work / f"key_{s['n']:02d}.png")
        return {"notes": ["Testlauf ohne GPU"], "gpu_seconds": 0}

    import modal
    from modal_app import Studio, app
    with modal.enable_output(), app.run():
        studio = Studio()
        for i, s in enumerate(shots):
            status(vid, state="running", progress=f"Bild {i + 1}/{len(shots)}")
            prompt = f"{style}. {s.get('image_prompt', '')}. vertical 9:16 composition"
            png = studio.keyframe.remote(prompt[:1800], seed=base + s["n"])
            (work / f"key_{s['n']:02d}.png").write_bytes(png)
            status(vid, state="running", progress=f"Animation {i + 1}/{len(shots)}")
            motion = f"{s.get('motion_prompt', '')}. {s.get('action', '')}. {s.get('camera', '')}"
            res = studio.animate.remote(png, motion[:1800], num_frames=121, seed=base + 100 + s["n"])
            (work / f"clip_{s['n']:02d}.mp4").write_bytes(res["mp4"])
            if res.get("note"):
                notes.append(f"Shot {s['n']}: {res['note']}")
            if res.get("mode") == "t2v":
                notes.append(f"Shot {s['n']}: ohne Startbild animiert (Figur evtl. weniger konsistent)")
    return {"notes": sorted(set(notes)), "gpu_seconds": round(time.time() - t0)}


# ----------------------------------------------------------------- 3 STIMMEN
_tts = {}


def voice_for(char):
    desc = f"{char.get('voice', '')} {char.get('role', '')} {char.get('design_sheet', '')}".lower()
    female = any(w in desc for w in ["female", "woman", "girl", "she ", "her ", "mother", "lady"])
    young = any(w in desc for w in ["teen", "boy", "girl", "young", "18", "17", "16"])
    if female:
        return "af_bella" if young else "af_heart"
    return "am_puck" if young else "am_michael"


def tts(text, voice, out):
    """Kokoro (Apache 2.0). Fallback: espeak-ng. Gibt Mono-Array mit SR zurück."""
    try:
        from kokoro import KPipeline
        if "p" not in _tts:
            _tts["p"] = KPipeline(lang_code="a")
        chunks = [a for _, _, a in _tts["p"](text, voice=voice, speed=0.95)]
        audio = np.concatenate([np.asarray(c, dtype=np.float32) for c in chunks])
        audio = resample_poly(audio, SR, 24000).astype(np.float32)
        _tts["engine"] = "Kokoro"
    except Exception as e:  # noqa: BLE001
        try:
            sh("espeak-ng", "-v", "en-us", "-s", "150", "-w", out, text)
            sr, a = wavfile.read(out)
            audio = resample_poly(a.astype(np.float32) / 32768, SR, sr).astype(np.float32)
            _tts["engine"] = f"espeak (Kokoro-Fehler: {repr(e)[:120]})"
        except Exception:  # noqa: BLE001
            audio = np.zeros(int(0.4 * SR * max(1, len(text.split()))), np.float32)
            _tts["engine"] = f"KEINE Stimme (Kokoro-Fehler: {repr(e)[:120]})"
    return audio


# ----------------------------------------------------------------- 4 SOUND (Freesound CC0)
def freesound(query, dur_filter, work, cache):
    if query in cache:
        return cache[query]
    key = os.environ.get("FREESOUND_API_KEY")
    if not key or not query:
        return None
    try:
        r = requests.get("https://freesound.org/apiv2/search/text/", timeout=30, params={
            "query": query, "token": key, "page_size": 10, "sort": "rating_desc",
            "filter": f'license:"Creative Commons 0" duration:{dur_filter}',
            "fields": "id,name,previews,duration"})
        r.raise_for_status()
        res = r.json().get("results", [])
        if not res:
            cache[query] = None
            return None
        pv = res[0]["previews"]
        url = pv.get("preview-hq-ogg") or pv.get("preview-hq-mp3")
        raw = work / f"fs_{res[0]['id']}.ogg"
        raw.write_bytes(requests.get(url, timeout=60).content)
        wav = raw.with_suffix(".wav")
        sh("ffmpeg", "-y", "-loglevel", "error", "-i", raw, "-ac", "1", "-ar", SR, wav)
        _, a = wavfile.read(wav)
        cache[query] = a.astype(np.float32) / 32768
    except Exception:  # noqa: BLE001
        cache[query] = None
    return cache[query]


def place(track, clip, start_s, gain_db=0.0):
    i = int(start_s * SR)
    if i >= len(track) or clip is None or not len(clip):
        return
    e = min(len(track), i + len(clip))
    track[i:e] += clip[: e - i] * (10 ** (gain_db / 20))


# ----------------------------------------------------------------- 5 SCHNITT
def ass_time(t):
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def produce(vid, no_gpu=False, max_shots=None):
    rec = json.loads((SCRIPTS / f"{vid}.json").read_text(encoding="utf-8"))
    sc = rec["script"]
    if max_shots:                                   # Test: nur die ersten N Shots (Guthaben schonen)
        sc["shots"] = sc["shots"][:max_shots]
    work = WORK / vid
    work.mkdir(parents=True, exist_ok=True)
    status(vid, state="running", progress="startet", title=sc.get("title"), youtube=sc.get("youtube"),
           started_at=now(), error=None)

    gpu = gpu_shots(vid, sc, work, no_gpu)
    status(vid, state="running", progress="Stimmen & Sound", gpu_seconds=gpu["gpu_seconds"])

    shots = sc["shots"]
    starts, t = [], 0.0
    for s in shots:
        starts.append(t)
        t += float(s.get("duration_s") or 5)
    end_len = 3.0
    total = t + end_len
    chars = {c.get("id"): c for c in sc.get("characters", [])}
    main_char = (sc.get("characters") or [{}])[0]

    # Stimmen
    vo = np.zeros(int(total * SR) + SR, np.float32)
    subs = []
    for s, st in zip(shots, starts):
        cur = st + 0.35
        lines = [(chars.get(d.get("character"), main_char), d.get("line")) for d in (s.get("dialogue") or [])]
        if s.get("voiceover"):
            lines.append((main_char, s["voiceover"]))
        for ch, text in lines:
            if not text:
                continue
            a = tts(text, voice_for(ch or {}), work / "tts.wav")
            place(vo, a, cur)
            subs.append((cur, cur + len(a) / SR + 0.2, text))
            cur += len(a) / SR + 0.25

    # Geräusche + Musik
    cache = {}
    sfx = np.zeros_like(vo)
    for s, st in zip(shots, starts):
        for q in (s.get("sfx") or [])[:2]:
            place(sfx, freesound(q, "[0.5 TO 20]", work, cache), st, -6)
    mood = (sc.get("music") or {}).get("mood", "tense")
    music_q = f"{mood} cinematic music"
    music = freesound(music_q, "[30 TO 600]", work, cache) or freesound("cinematic tension drone", "[30 TO 600]", work, cache)
    bed = np.zeros_like(vo)
    if music is not None:
        reps = int(np.ceil(len(bed) / len(music)))
        bed = np.tile(music, reps)[: len(bed)]
        env = np.convolve((np.abs(vo) > 0.01).astype(np.float32), np.ones(SR // 4) / (SR // 4), "same")
        bed *= (10 ** (-17 / 20)) * (1 - 0.6 * np.clip(env * 3, 0, 1))     # leiser, wenn gesprochen wird
        fade = int(1.5 * SR)
        bed[:fade] *= np.linspace(0, 1, fade)
        bed[int((total - 2) * SR):] *= np.linspace(1, 0, len(bed) - int((total - 2) * SR))
    mix = vo * 1.0 + sfx + bed
    mix = np.clip(mix / max(1.0, np.max(np.abs(mix)) / 0.95), -1, 1)
    wavfile.write(work / "mix.wav", SR, (np.stack([mix, mix], 1) * 32767).astype(np.int16))

    # Video: Clips auf Shot-Länge bringen, aneinanderhängen, Endtafel
    status(vid, state="running", progress="Schnitt")
    segs = []
    for s in shots:
        clip = work / f"clip_{s['n']:02d}.mp4"
        dur = float(s.get("duration_s") or 5)
        clen = float(sh("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", clip) or 5)
        factor = max(1.0, min(1.8, dur / max(clen, 0.5)))           # leichte Zeitlupe, falls Shot länger
        seg = work / f"seg_{s['n']:02d}.mp4"
        sh("ffmpeg", "-y", "-loglevel", "error", "-i", clip, "-vf",
           f"setpts={factor:.3f}*PTS,scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,"
           f"crop={W}:{H},fps={FPS},tpad=stop_mode=clone:stop_duration=3",
           "-t", f"{dur:.2f}", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", seg)
        segs.append(seg)
    endc = work / "endcard.mp4"
    sh("ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:d={end_len}:r={FPS}",
       "-vf", f"drawtext=fontfile={FONT}:text='{END_CARD}':fontsize=44:fontcolor=white:x=(w-tw)/2:y=(h-th)/2,"
              f"fade=t=in:d=0.6", "-c:v", "libx264", "-pix_fmt", "yuv420p", endc)
    segs.append(endc)
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in segs))
    joined = work / "joined.mp4"
    sh("ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", joined)

    # Untertitel (Anime-typisch: weiß, dicke Kontur, unten mittig)
    ass = work / "subs.ass"
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
            "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
            "MarginR, MarginV, Encoding\n"
            "Style: S,DejaVu Sans,62,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,5,2,2,80,80,330,1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    ev = [f"Dialogue: 0,{ass_time(a)},{ass_time(b)},S,,0,0,0,,{{\\fad(120,120)}}{x.replace('{', '(').replace('}', ')')}"
          for a, b, x in subs]
    ass.write_text(head + "\n".join(ev) + "\n", encoding="utf-8")

    final = work / f"{vid}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", joined.name, "-i", "mix.wav",
                    "-vf", f"subtitles={ass.name}", "-map", "0:v", "-map", "1:a",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-r", str(FPS),
                    "-af", "loudnorm=I=-14:TP=-1.5:LRA=9", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                    "-shortest", "-movflags", "+faststart", final.name], cwd=work, check=True)
    poster = work / "poster.jpg"
    sh("ffmpeg", "-y", "-loglevel", "error", "-ss", "1.5", "-i", final, "-frames:v", "1", "-vf", "scale=540:-2", poster)

    # Ablage als GitHub-Release (öffentlicher Link fürs Dashboard und später für Instagram/TikTok)
    urls = upload_release(vid, sc.get("title") or vid, [final, poster])
    notes = gpu["notes"] + [f"Stimmen: {_tts.get('engine', '–')}",
                            "Musik: " + ("Freesound CC0" if music is not None else "keine gefunden")]
    status(vid, state="done", progress="fertig", video_url=urls.get(final.name), poster_url=urls.get(poster.name),
           duration_s=round(total, 1), notes=notes, finished_at=now())
    print(f"  ✓ {vid}: {urls.get(final.name)}")


def upload_release(vid, title, files):
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo or not os.environ.get("GH_TOKEN"):
        return {f.name: str(f) for f in files}
    tag = f"short-{vid}"
    exists = subprocess.run(["gh", "release", "view", tag, "--repo", repo], capture_output=True).returncode == 0
    if exists:
        sh("gh", "release", "upload", tag, *files, "--clobber", "--repo", repo)
    else:
        sh("gh", "release", "create", tag, *files, "--repo", repo, "--title", f"Short: {title}",
           "--notes", f"Automatisch produziert von KI 3. {END_CARD}")
    return {f.name: f"https://github.com/{repo}/releases/download/{tag}/{f.name}" for f in files}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--id")
    ap.add_argument("--no-gpu", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--max", type=int, default=1, help="max. Shorts pro Lauf (Guthaben schonen)")
    ap.add_argument("--max-shots", type=int, default=0, help="Test: nur die ersten N Shots")
    a = ap.parse_args()
    if a.id:
        if not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", a.id):
            sys.exit("Ungültige ID")
        ids = [a.id]
    else:
        ids = []
        for f in sorted(SCRIPTS.glob("*.json")):
            r = json.loads(f.read_text(encoding="utf-8"))
            p = PROD / f.name
            st = json.loads(p.read_text(encoding="utf-8")).get("state") if p.exists() else None
            if r.get("status") == "approved" and (st not in ("done",) or a.force):
                ids.append(r["video_id"])
        ids = ids[: a.max]
    print(f"KI 3: {ids or 'nichts zu tun'}")
    for vid in ids:
        try:
            produce(vid, a.no_gpu, a.max_shots or None)
        except Exception as e:  # noqa: BLE001
            status(vid, state="error", error=f"{e}\n{traceback.format_exc()[-1500:]}"[:3000])
            print(f"  ⚠ {vid}: {e}")
    build_index()


if __name__ == "__main__":
    main()
