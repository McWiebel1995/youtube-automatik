#!/usr/bin/env python3
"""
Neuer Kanal (Arbeitstitel „Ruhige Gedanken“): ruhige, kluge Gedanken zum Zuhören und Einschlafen.

  Text:  Gemini schreibt einen neuen, warmen Erzähltext (Deutsch)
  Stimme: Gemini TTS (High-End, Stil per Anweisung: ruhig, warm, mit Pausen)
  Bild:  echte Naturvideos (Pixabay/Pexels, 1080p), lange ruhige Einstellungen
  Ton:   Stimme vorn, leise Naturatmosphäre darunter (Freesound CC0, ohne Tiere/Menschen)

    python scripts/gedanken.py --out output/gedanken-test [--minutes 12] [--voice Sulafat]

Ergebnis: video.mp4 (16:9, ~10–14 Min.), short.mp4 (9:16, ~45 s), meta.json
"""
import argparse
import base64
import json
import os
import random
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np
import requests
from scipy.io import wavfile
from scipy.signal import resample_poly

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT / "anime")]
import gemini  # noqa: E402

SR = 48000
TTS_MODELS = ["gemini-2.5-flash-preview-tts", "gemini-2.5-flash-tts", "gemini-2.5-pro-preview-tts"]
STYLE = ("Sprich wie eine erfahrene, warmherzige Erzählerin in einem ruhigen Hörbuch zum Einschlafen: langsam, "
         "sanft, nah am Mikrofon, mit natürlichen Pausen nach jedem Gedanken. Nicht theatralisch, sondern "
         "ruhig, klug und zugewandt. Lies den folgenden Text vor:\n\n")
TOPICS = ["Gelassenheit im Alltag", "Lernen mit Neugier wie ein Kind", "Fehler als Lehrer", "Wirklich zuhören",
          "Dankbarkeit am Abend", "Loslassen, was wir nicht ändern können", "Gedanken ordnen vor dem Schlafen",
          "Warum unser Gehirn Geschichten liebt", "Die Kraft der Langsamkeit", "Staunen über kleine Dinge",
          "Gute Gespräche", "Mit sich selbst freundlich sein", "Gewohnheiten, die uns tragen", "Stille aushalten",
          "Wie Erinnerungen entstehen", "Mut zu kleinen Schritten"]
SCENES = ["misty forest morning", "calm lake sunrise", "mountain valley clouds", "forest stream", "ocean waves sunset",
          "rain on leaves", "foggy hills", "autumn forest", "snowy forest", "river flowing slowly", "meadow wind grass"]
AMBIENT = {"forest stream": "stream creek", "rain on leaves": "gentle rain", "ocean waves sunset": "ocean waves calm",
           "default": "soft wind trees"}

TEXT_TASK = """Schreibe einen neuen, ruhigen Hörtext auf Deutsch zum Thema „{topic}“.
Stil: warm, klug, persönlich (Du-Form), wie eine kluge, humorvolle Lehrerin, die abends am Kamin erzählt.
Anschauliche Beispiele aus dem Alltag, kleine überraschende Erkenntnisse (z. B. wie das Gehirn lernt),
keine Ratgeber-Floskeln, keine Aufzählungen, keine Esoterik, keine medizinischen Versprechen.
Baue genau {nq} passende Zitate aus DIESER Liste wörtlich ein (nicht verändern, keine anderen Zitate erfinden),
jeweils mit Namen eingeleitet (z. B. „Seneca hat einmal geschrieben: …“) und danach einen Moment zum Nachdenken:
{quotes}
Außer diesen Zitat-Autoren keine Namen realer Personen. Zum Ende hin immer ruhiger, der Schluss lädt zum Entspannen und Einschlafen ein.
Länge: {words} Wörter in {paras} Absätzen.
Zusätzlich: ein „Gedanke des Tages“ (35–50 Wörter) für einen Kurzclip, der für sich allein steht.
Antworte NUR mit JSON:
{{"title": "...", "paragraphs": ["..."], "short_thought": "...",
  "quotes": [{{"text": "exakt wie in der Liste", "author": "...", "paragraph": Index des Absatzes (0-basiert)}}],
  "youtube": {{"title": "max 90 Zeichen, z. B. 'Gelassenheit lernen – ruhige Gedanken zum Einschlafen'",
              "description": "3–5 Sätze", "tags": ["..."]}},
  "short_title": "max 80 Zeichen, endet mit #shorts"}}"""


# ----------------------------------------------------------------- Text
def write_text(rnd, minutes):
    topic = rnd.choice(TOPICS)
    words = int(minutes * 120)                    # ruhiges Vorlesetempo ~120 Wörter/Minute
    import yaml
    pool = yaml.safe_load((ROOT / "data" / "quotes.yaml").read_text(encoding="utf-8"))
    sample = rnd.sample(pool, min(12, len(pool)))
    qlist = "\n".join(f"- „{q['text']}“ – {q['author']}" for q in sample)
    data = gemini.ask_json(TEXT_TASK.format(topic=topic, words=words, paras=max(10, words // 110), nq=rnd.choice([2, 3]),
                                            quotes=qlist), temperature=0.9)
    data["topic"] = topic
    w = sum(len(x.split()) for x in data["paragraphs"])
    if w < words * 0.75:                                   # zu kurz -> ausbauen lassen
        more = gemini.ask_json(
            f"Erweitere diesen Hörtext auf {words} Wörter in {max(12, words // 110)} Absätzen. Gleicher Ton, gleiche "
            "Zitate (wörtlich, nicht verändern), mehr anschauliche Beispiele und ruhige Momente. Antworte NUR mit JSON "
            '{"paragraphs": ["..."], "quotes": [{"text": "...", "author": "...", "paragraph": 0}]}\n\n'
            + json.dumps({"paragraphs": data["paragraphs"], "quotes": data.get("quotes")}, ensure_ascii=False),
            temperature=0.7)
        if sum(len(x.split()) for x in more.get("paragraphs", [])) > w:
            data["paragraphs"], data["quotes"] = more["paragraphs"], more.get("quotes", data.get("quotes"))
    valid = {q["text"]: q["author"] for q in pool}
    data["quotes"] = [q for q in (data.get("quotes") or []) if q.get("text") in valid
                      and valid[q["text"]] == q.get("author")]          # nur geprüfte Zitate anzeigen
    return data


# ----------------------------------------------------------------- Stimme (Gemini TTS)
def tts(text, voice, out_wav, key=None):
    import gtts
    m = gtts.synth(text, voice, out_wav, style=STYLE, key=key)
    time.sleep(gtts.GAP_S)
    return m


def read_wav(path):
    sr, a = wavfile.read(path)
    a = a.astype(np.float32) / 32768
    if a.ndim > 1:
        a = a.mean(axis=1)
    return resample_poly(a, SR, sr).astype(np.float32) if sr != SR else a


def trim_silence(a, thr=0.004):
    idx = np.where(np.abs(a) > thr)[0]
    return a[max(0, idx[0] - 800): idx[-1] + 2400] if len(idx) else a


def chunks(paragraphs, max_words=300):
    """Absätze zu wenigen größeren Stücken bündeln (weniger TTS-Anfragen -> schont das Gratis-Kontingent)."""
    out, cur = [], []
    for p in paragraphs:
        if cur and len(" ".join(cur + [p]).split()) > max_words:
            out.append("\n\n".join(cur))
            cur = []
        cur.append(p)
    if cur:
        out.append("\n\n".join(cur))
    return out


def sentences(text):
    import re
    return [x for x in re.split(r"(?<=[.!?…])\s+", text.strip()) if x]


def cb_paragraph(p, work, tag):
    """Chatterbox (deutsche Referenzstimme): je 1–2 Sätze pro Anfrage, natürliche kurze Pausen."""
    sys.path.insert(0, str(HERE / "kids"))
    import tts as ktts
    groups, cur = [], []
    for s_ in sentences(p):
        cur.append(s_)
        if len(" ".join(cur).split()) >= 22:
            groups.append(" ".join(cur))
            cur = []
    if cur:
        groups.append(" ".join(cur))
    out = []
    for j, g in enumerate(groups):
        f = work / f"{tag}_{j:02d}.wav"
        ktts.speak(g, f, style="ruhig")
        out += [trim_silence(read_wav(f)), np.zeros(int(0.45 * SR), np.float32)]
    return np.concatenate(out) if out else np.zeros(1, np.float32)


def voice_track(paragraphs, voice, work, starts=None):
    parts, model = [np.zeros(int(3.0 * SR), np.float32)], None
    if os.environ.get("TTS_ENGINE") == "chatterbox":
        t = 3.0
        for i, p in enumerate(paragraphs):
            a = cb_paragraph(p, work, f"p{i:02d}")
            if starts is not None:
                starts.append(t)
            parts += [a, np.zeros(int(1.2 * SR), np.float32)]
            t += len(a) / SR + 1.2
        parts.append(np.zeros(int(8 * SR), np.float32))
        return np.concatenate(parts), "chatterbox-de"
    for i, p in enumerate(chunks(paragraphs)):
        model = tts(p, voice, work / f"v{i:02d}.wav")
        parts += [trim_silence(read_wav(work / f"v{i:02d}.wav")), np.zeros(int(1.6 * SR), np.float32)]
    parts.append(np.zeros(int(8 * SR), np.float32))
    return np.concatenate(parts), model


# ----------------------------------------------------------------- Bild (echte Naturvideos)
def fetch_clips(queries, work, need=6):
    import fetch_stock as fs
    sources = []
    if os.environ.get("PEXELS_API_KEY"):
        sources.append((fs.search_pexels, os.environ["PEXELS_API_KEY"]))
    if os.environ.get("PIXABAY_API_KEY"):
        sources.append((fs.search_pixabay, os.environ["PIXABAY_API_KEY"]))
    clips = []
    for q in queries:
        for search, key in sources:
            try:
                hits = list(search(key, q))[:3]
            except requests.RequestException:
                continue
            for cid, url, _ in hits:
                dst = work / f"src_{cid}.mp4"
                try:
                    with requests.get(url, stream=True, timeout=180) as dl:
                        dl.raise_for_status()
                        with open(dst, "wb") as f:
                            for ch in dl.iter_content(1 << 20):
                                f.write(ch)
                    clips.append(dst)
                    break
                except Exception:  # noqa: BLE001
                    dst.unlink(missing_ok=True)
            if len(clips) >= need:
                return clips
    return clips


def normalize(src, dst, seconds):
    """1080p/30, sanft verlangsamt (ruhiger), weiche Ein-/Ausblendung, bei Bedarf hin und zurück geloopt."""
    d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(src)],
                             capture_output=True, text=True).stdout or 10)
    vf = ("scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,setpts=1.25*PTS,fps=30,"
          f"eq=saturation=0.95:brightness=-0.02,fade=t=in:d=1.2,fade=t=out:st={seconds - 1.2}:d=1.2,format=yuv420p")
    loop = ["-stream_loop", "-1"] if d * 1.25 < seconds else []
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *loop, "-i", str(src), "-t", f"{seconds}", "-an", "-vf", vf,
                    "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-profile:v", "high", str(dst)], check=True)


def ambient(scene, seconds, work):
    """Leise Naturatmosphäre (Freesound CC0, gleiche Filter wie Calm Haven)."""
    try:
        import fetch_sounds as fsd
        key = os.environ.get("FREESOUND_API_KEY")
        q = AMBIENT.get(scene, AMBIENT["default"])
        for s, url in fsd.search(key, q):
            raw = work / "amb.ogg"
            raw.write_bytes(requests.get(url, timeout=120).content)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", str(raw), "-t",
                            f"{seconds}", "-ac", "1", "-ar", str(SR), str(work / "amb.wav")], check=True)
            return read_wav(work / "amb.wav")
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ Atmosphäre: {e}")
    return np.zeros(int(seconds * SR), np.float32)


MUSIC_Q = ["calm ambient piano", "soft piano relaxing", "ambient pad calm meditation", "gentle piano ambient"]


def ambient_music(seconds, work):
    """Entspannte Hintergrundmusik (Freesound CC0, ohne Gesang), mehrere Stücke weich aneinandergereiht."""
    import fetch_sounds as fsd
    key = os.environ.get("FREESOUND_API_KEY")
    out, n = [], int(seconds * SR)
    try:
        for q in random.sample(MUSIC_Q, len(MUSIC_Q)):
            for s, url in fsd.search(key, q):
                if {"vocal", "vocals", "voice", "singing", "drums", "beat"} & {t.lower() for t in s.get("tags", [])}:
                    continue
                raw = work / f"mus_{s['id']}.ogg"
                raw.write_bytes(requests.get(url, timeout=120).content)
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-ac", "1", "-ar", str(SR),
                                str(raw.with_suffix(".wav"))], check=True)
                a = read_wav(raw.with_suffix(".wav"))
                f = min(len(a) // 4, 4 * SR)
                a[:f] *= np.linspace(0, 1, f)
                a[-f:] *= np.linspace(1, 0, f)
                out.append(a)
                break
            if sum(len(x) for x in out) >= n:
                break
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ Musik: {e}")
    if not out:
        return np.zeros(n, np.float32)
    track = np.concatenate(out)
    track = np.tile(track, int(np.ceil(n / len(track))) + 1)[:n]
    return track.astype(np.float32)


def font(name):
    p = ROOT / "assets" / "fonts" / name
    return p if p.exists() else Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


def esc(t):
    return t.replace("\\", "").replace(":", "\\:").replace("'", "’").replace("%", "")


def build(out: Path, minutes=12.0, voice="Sulafat", seed=None):
    rnd = random.Random(seed)
    out = Path(out).resolve()                     # absolute Pfade (ffmpeg läuft im Arbeitsordner)
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=out))
    print("▶ Text …")
    data = write_text(rnd, minutes)
    print(f"  „{data['title']}“ ({data['topic']}), {sum(len(p.split()) for p in data['paragraphs'])} Wörter")
    print("▶ Stimme …")
    pstarts = []
    v, model = voice_track(data["paragraphs"], voice, work, pstarts)
    total = len(v) / SR
    scene_pool = rnd.sample(SCENES, 5)
    print(f"  {total / 60:.1f} Min. ({model}) ▶ Bilder: {scene_pool}")
    srcs = fetch_clips(scene_pool, work)
    if not srcs:
        raise RuntimeError("Keine Naturvideos gefunden (PEXELS_API_KEY / PIXABAY_API_KEY?)")
    seg = 90.0                                    # lange, ruhige Einstellungen
    n = int(np.ceil(total / seg))
    segs = []
    for i in range(n):
        dst = work / f"seg_{i:02d}.mp4"
        normalize(srcs[i % len(srcs)], dst, seg)
        segs.append(dst)
    (work / "list.txt").write_text("".join(f"file '{p.name}'\n" for p in segs))
    amb = ambient(scene_pool[0], total + 2, work)
    amb = np.pad(amb, (0, max(0, len(v) + 60 * SR - len(amb))))   # nie kürzer als Stimme (+ Short)
    mus = ambient_music(total + 60, work)                          # sanfte Hintergrundmusik
    mix = v * 1.0 + amb[: len(v)] * (10 ** (-26 / 20)) + mus[: len(v)] * (10 ** (-25 / 20))
    fo = int(6 * SR)
    mix[-fo:] *= np.linspace(1, 0, fo)
    mix = np.clip(mix / max(1e-6, np.max(np.abs(mix))) * 0.9, -1, 1)
    wavfile.write(work / "mix.wav", SR, (mix * 32767).astype(np.int16))
    (work / "title.txt").write_text(data["title"], encoding="utf-8")
    tf = font("CormorantGaramond.ttf")
    vf = (f"drawtext=fontfile={tf}:textfile=title.txt:fontsize=88:fontcolor=white:x=(w-tw)/2:y=(h-th)/2:"
          "shadowcolor=black@0.5:shadowx=2:shadowy=2:alpha='if(lt(t,1),0,if(lt(t,2.5),(t-1)/1.5,if(lt(t,7),1,"
          "if(lt(t,9),(9-t)/2,0))))',"
          f"fade=t=out:st={total - 3}:d=3")
    qf = font("PlayfairDisplay.ttf")
    import textwrap
    for k, q in enumerate(data.get("quotes") or []):
        i = q.get("paragraph")
        if not isinstance(i, int) or not 0 <= i < len(pstarts):
            continue
        t0, t1 = pstarts[i] + 2, pstarts[i] + 16
        qlines = textwrap.wrap(q["text"], 42)
        (work / f"q{k}.txt").write_text("„" + "\n".join(qlines) + "“", encoding="utf-8")
        ay = f"h*0.62+{len(qlines) * 76 + 26}"
        (work / f"a{k}.txt").write_text("– " + q["author"], encoding="utf-8")
        al = f"if(lt(t,{t0}),0,if(lt(t,{t0 + 1.5}),(t-{t0})/1.5,if(lt(t,{t1 - 1.5}),1,if(lt(t,{t1}),({t1}-t)/1.5,0))))"
        vf += (f",drawtext=fontfile={qf}:textfile=q{k}.txt:fontsize=58:line_spacing=16:fontcolor=white:"
               f"x=(w-tw)/2:y=h*0.62:shadowcolor=black@0.6:shadowx=2:shadowy=2:alpha='{al}'"
               f",drawtext=fontfile={qf}:textfile=a{k}.txt:fontsize=40:fontcolor=white@0.85:"
               f"x=(w-tw)/2:y={ay}:shadowcolor=black@0.6:shadowx=2:shadowy=2:alpha='{al}'")
    print("▶ Schnitt …")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "list.txt", "-i", "mix.wav",
                    "-vf", vf, "-map", "0:v", "-map", "1:a", "-t", f"{total:.2f}", "-c:v", "libx264", "-preset", "medium",
                    "-crf", "20", "-profile:v", "high", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                    "-af", "loudnorm=I=-18:TP=-1.5:LRA=7", "-movflags", "+faststart", str(out / "video.mp4")],
                   cwd=work, check=True)

    print("▶ Short …")
    if os.environ.get("TTS_ENGINE") == "chatterbox":
        st = cb_paragraph(data["short_thought"], work, "short")
    else:
        tts(data["short_thought"], voice, work / "short.wav")
        st = trim_silence(read_wav(work / "short.wav"))
    sv = np.concatenate([np.zeros(int(1.0 * SR), np.float32), st, np.zeros(int(2.5 * SR), np.float32)])
    sdur = min(58.0, len(sv) / SR)
    sm = sv[: int(sdur * SR)] + amb[: int(sdur * SR)] * (10 ** (-24 / 20)) + mus[: int(sdur * SR)] * (10 ** (-23 / 20))
    sm = np.clip(sm / max(1e-6, np.max(np.abs(sm))) * 0.9, -1, 1)
    wavfile.write(work / "smix.wav", SR, (sm * 32767).astype(np.int16))
    import textwrap
    lines = textwrap.wrap(data["short_thought"], 26)
    (work / "thought.txt").write_text("\n".join(lines), encoding="utf-8")
    (work / "kicker.txt").write_text("Gedanke des Tages", encoding="utf-8")
    bf = font("PlayfairDisplay.ttf")
    svf = ("scale=-2:1920,crop=1080:1920,setpts=1.25*PTS,eq=brightness=-0.10,"
           "drawbox=x=0:y=ih*0.18:w=iw:h=ih*0.62:color=black@0.32:t=fill,"
           f"drawtext=fontfile={bf}:textfile=kicker.txt:fontsize=58:fontcolor=white@0.85:x=(w-tw)/2:y=330,"
           f"drawtext=fontfile={bf}:textfile=thought.txt:fontsize=64:line_spacing=18:fontcolor=white:"
           "x=(w-tw)/2:y=(h-th)/2:shadowcolor=black@0.6:shadowx=2:shadowy=2:alpha='min(1,t/1.5)',"
           f"fade=t=in:d=0.8,fade=t=out:st={sdur - 1.5}:d=1.5,format=yuv420p")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", str(srcs[0]), "-i", "smix.wav",
                    "-vf", svf, "-map", "0:v", "-map", "1:a", "-t", f"{sdur:.2f}", "-c:v", "libx264", "-preset",
                    "medium", "-crf", "19", "-c:a", "aac", "-b:a", "192k", "-af", "loudnorm=I=-16:TP=-1.5",
                    "-movflags", "+faststart", str(out / "short.mp4")], cwd=work, check=True)
    meta = {k: data.get(k) for k in ("title", "topic", "short_thought", "youtube", "short_title", "quotes")}
    meta.update(minutes=round(total / 60, 1), voice=voice, tts_model=model, scenes=scene_pool)
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    subprocess.run(["rm", "-rf", str(work)])
    print(f"  ✓ {out / 'video.mp4'} ({total / 60:.1f} Min.) + short.mp4")
    return meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output/gedanken-test")
    ap.add_argument("--minutes", type=float, default=12)
    ap.add_argument("--voice", default="Sulafat")
    ap.add_argument("--seed", type=int)
    a = ap.parse_args()
    build(Path(a.out), a.minutes, a.voice, a.seed)
