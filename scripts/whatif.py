#!/usr/bin/env python3
"""
Beyond the If – automatische „What if…?“-Videos (Englisch).

  1 THEMA      Gemini schlägt eine neue What-if-Frage vor (keine Wiederholungen)
  2 RECHERCHE  Gemini mit Google-Suche (Fakten + Quellen)
  3 SKRIPT     Erzählung in Abschnitten, je Abschnitt ein Bild: echtes Stock-Video ODER KI-Bild (FLUX)
  4 STIMME     Chatterbox (englisch) mit Erzähler-Referenzstimme, Satz für Satz
  5 SCHNITT    1080p, einheitlicher Look (Farbe, Überblendungen, Kamerafahrten), Untertitel, Musik
  6 SHORTS     2 Hochkant-Shorts aus demselben Material
  7 UPLOAD     YouTube (+ Instagram-Vormerkung)

    python scripts/whatif.py --out output/whatif-test [--dry-run]
"""
import argparse
import datetime as dt
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import numpy as np
import requests
import yaml
from scipy.io import wavfile
from scipy.signal import resample_poly

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT / "anime")]
import gemini  # noqa: E402

SR = 48000
FPS = 30
USED = ROOT / "data" / "whatif_used.json"
CFG = yaml.safe_load((ROOT / "config" / "whatif.yaml").read_text(encoding="utf-8"))["channel"]
FONT = ROOT / "assets" / "fonts" / "Montserrat.ttf"
GRADE = "eq=contrast=1.05:saturation=1.05,colorbalance=rs=0.02:bs=0.03:rh=0.03:bh=-0.02"   # einheitlicher Look

TOPIC_TASK = """You run the YouTube channel "Beyond the If" (curious, science-based what-if scenarios, English).
Suggest ONE fresh, highly clickable what-if question that can be answered with real science
(physics, space, biology, earth, history, technology). Avoid these already used topics: {used}
Answer ONLY JSON: {{"question": "What if ...?", "angle": "one sentence: what makes it fascinating"}}"""

SCRIPT_TASK = """Write the script for a YouTube video of the channel "Beyond the If".
Question: {question}
Research notes (facts you may use – do not invent numbers beyond these):
{notes}

Style: gripping documentary narration like Kurzgesagt/What If – curious, vivid, a little dramatic, clear science,
second person sometimes ("Imagine you…"). Start with a strong 2-sentence hook. Build up step by step
(first seconds, first days, years later…). End with a thought-provoking twist and a question to the viewer.
Length: {words} words in {segs} segments (2–4 sentences each).
For EVERY segment choose ONE visual:
  - "stock": real footage that exists (space, nature, cities, labs…) -> give a short English search query (2–4 words)
  - "ai": a scene that cannot be filmed (Earth without Moon, giant tsunami over a city…) -> give a detailed,
    photorealistic cinematic image prompt (wide shot, lighting, 16:9, no text)
Mix both; about half "ai". Keep every visual safe (no gore, no real people).
Also write 2 YouTube Shorts (each 60–85 words, standalone, strong hook in the first sentence, ending with
"Full video on the channel."), each using 3–4 of the segment visuals (by index).
Answer ONLY JSON:
{{"title": "max 70 chars, clickable, no clickbait lies", "segments": [{{"text": "...", "visual": {{"kind": "stock|ai",
  "query": "...", "prompt": "..."}}}}], "shorts": [{{"title": "max 80 chars incl #shorts", "text": "...",
  "visuals": [0, 3, 5]}}], "description": "3–4 sentences", "tags": ["..."]}}"""


def now():
    return dt.datetime.now(dt.timezone.utc)


def used():
    return json.loads(USED.read_text(encoding="utf-8")) if USED.exists() else []


# ----------------------------------------------------------------- 1–3 Text
UA = {"User-Agent": "BeyondTheIf/1.0 (YouTube science channel; github.com/McWiebel1995)"}


def google_news(query, n=12):
    """Aktuelle Schlagzeilen (Google News RSS) – als Themen-Inspiration und Quellenhinweise."""
    import xml.etree.ElementTree as ET
    try:
        r = requests.get("https://news.google.com/rss/search", params={"q": query, "hl": "en-US", "gl": "US",
                                                                         "ceid": "US:en"}, headers=UA, timeout=30)
        r.raise_for_status()
        items = ET.fromstring(r.content).findall(".//item")[:n]
        return [(i.findtext("title") or "", i.findtext("link") or "") for i in items]
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ Google News: {e}")
        return []


def wikipedia(query, n=3):
    """Faktenbasis aus Wikipedia (Zusammenfassungen + Links)."""
    out = []
    try:
        r = requests.get("https://en.wikipedia.org/w/api.php", headers=UA, timeout=30, params={
            "action": "query", "list": "search", "srsearch": query, "srlimit": n, "format": "json"})
        for hit in r.json().get("query", {}).get("search", []):
            t = hit["title"]
            sm = requests.get("https://en.wikipedia.org/api/rest_v1/page/summary/" + requests.utils.quote(t),
                              headers=UA, timeout=30).json()
            out.append((t, sm.get("extract", ""), (sm.get("content_urls") or {}).get("desktop", {}).get("page", "")))
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ Wikipedia: {e}")
    return out


def plan(rnd, minutes):
    u = used()[-60:]
    news = google_news(rnd.choice(["science discovery", "space astronomy", "physics breakthrough", "climate earth science",
                                   "biology evolution", "future technology"]))
    news_txt = "\n".join(f"- {t}" for t, _ in news) or "none"
    topic = gemini.ask_json(TOPIC_TASK.format(used="; ".join(u) or "none") +
                            f"\nOptional inspiration – current science headlines (Google News):\n{news_txt}",
                            temperature=1.0)
    q = topic["question"]
    try:
        notes, sources = gemini.research(
            f"Research the scientific facts for the question: {q}\nGive key facts, numbers, timelines and consequences "
            f"with brief explanations. Be accurate; mention uncertainties.")
    except Exception as e:  # noqa: BLE001
        print(f"::warning title=Recherche::{str(e)[:900]}")
        notes, sources = "", []
    # Zusätzlich / ersatzweise: Wikipedia-Fakten + aktuelle Meldungen (Google News) zum Thema
    kw = re.sub(r"(?i)^what if\s+", "", q).rstrip("?")
    wiki = wikipedia(kw)
    if len(wiki) < 2:                                      # Frage als Suchtext findet oft nichts -> Fachbegriffe
        try:
            terms = gemini.ask_json(f"List 3 exact English Wikipedia article titles with the core science behind: {q}. "
                                    'Answer JSON: {"titles": ["...", "...", "..."]}', temperature=0.2)["titles"]
            for t in terms[:3]:
                wiki += wikipedia(t, 1)
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ Wikipedia-Begriffe: {e}")
        seen = set()
        wiki = [w for w in wiki if not (w[0] in seen or seen.add(w[0]))]
    nws = google_news(kw, 6)
    notes += "\n\nWikipedia facts:\n" + "\n".join(f"[{t}] {x[:1500]}" for t, x, _ in wiki)
    notes += "\n\nRecent news headlines:\n" + "\n".join(f"- {t}" for t, _ in nws)
    if not wiki and not sources:
        notes += ("\nUse only well-established, widely accepted scientific facts; avoid precise numbers unless they "
                  "are textbook knowledge.")
    sources = sources + [(f"Wikipedia: {t}", url) for t, _, url in wiki if url] + [(t, url) for t, url in nws[:3]]
    words = int(minutes * 140)
    script = gemini.ask_json(SCRIPT_TASK.format(question=q, notes=notes[:12000], words=words,
                                                segs=max(10, words // 60)), temperature=0.8)
    for _ in range(2):
        have = sum(len(sg.get("text", "").split()) for sg in script.get("segments", []))
        if have >= words * 0.9:
            break
        print(f"  Skript zu kurz ({have}/{words} Wörter) – verlängere …")
        script = gemini.ask_json(
            f"This script has only {have} words but needs {words} words. Expand it to {words} words: add more "
            f"segments and vivid details (same facts, same style, same JSON format, keep the shorts).\n\n"
            + json.dumps(script, ensure_ascii=False), temperature=0.7)
    script["question"] = q
    script["sources"] = [s for s in sources if s[1]][:8]
    return script


# ----------------------------------------------------------------- 4 Stimme
def sentences(t):
    return [x for x in re.split(r"(?<=[.!?])\s+", t.strip()) if x]


def to_sr(wav_bytes, work, name):
    p = work / name
    p.write_bytes(wav_bytes)
    sr, a = wavfile.read(p)
    a = a.astype(np.float32) / (32768 if a.dtype == np.int16 else 1)
    if a.ndim > 1:
        a = a.mean(axis=1)
    a = resample_poly(a, SR, sr).astype(np.float32) if sr != SR else a
    idx = np.where(np.abs(a) > 0.004)[0]
    return a[max(0, idx[0] - 600): idx[-1] + 2400] if len(idx) else a


def narrate(voice, ref, texts, work, tag):
    """Gibt (Audio, [(start, ende, satz)]) zurück."""
    parts, subs, t = [], [], 0.0
    for i, s in enumerate(texts):
        a = to_sr(voice.speak.remote(s, ref, exaggeration=0.6, cfg_weight=0.45, seed=3 + i), work, f"{tag}_{i}.wav")
        subs.append((t, t + len(a) / SR, s))
        parts += [a, np.zeros(int(0.28 * SR), np.float32)]
        t += len(a) / SR + 0.28
    return (np.concatenate(parts) if parts else np.zeros(SR, np.float32)), subs


# ----------------------------------------------------------------- 5 Bilder
OFFTOPIC = {"laptop", "computer", "phone", "smartphone", "keyboard", "office", "desk", "woman", "man", "person",
            "people", "girl", "boy", "selfie", "food", "kitchen", "candle", "toy", "studio", "product", "logo"}
STOP = {"a", "an", "the", "of", "in", "on", "and", "with", "at", "to", "from", "over", "under", "by"}


def relevant(query, desc):
    """Clip passt nur, wenn die Beschreibung ein Wort der Suche enthält und nichts Themenfremdes zeigt."""
    if not desc:
        return True
    q = {w.rstrip("s") for w in re.findall(r"[a-z]+", query.lower())} - STOP
    d = {w.rstrip("s") for w in re.findall(r"[a-z]+", desc.lower())}
    return bool(q & d) and not ({w.rstrip("s") for w in OFFTOPIC} & d - q)


def stock_clip(query, work, used_ids):
    import fetch_stock as fs
    for fn, key in [(fs.search_pexels, os.environ.get("PEXELS_API_KEY")), (fs.search_pixabay, os.environ.get("PIXABAY_API_KEY"))]:
        if not key:
            continue
        try:
            for cid, url, _ in list(fn(key, query))[:12]:
                if cid in used_ids or not relevant(query, fs.DESC.get(cid, "")):
                    continue
                dst = work / f"src_{cid}.mp4"
                with requests.get(url, stream=True, timeout=180) as r:
                    r.raise_for_status()
                    with open(dst, "wb") as f:
                        for ch in r.iter_content(1 << 20):
                            f.write(ch)
                used_ids.add(cid)
                return dst
        except Exception:  # noqa: BLE001
            continue
    return None


def segment_video(src, dst, seconds, is_image, w=1920, h=1080, seed=0):
    """Einheitlicher Look: gleiche Farbkorrektur, sanfte Bewegung, gleiche Bildrate."""
    if is_image:
        frames = int(seconds * FPS) + 2
        zin = random.Random(seed).random() < 0.5
        z = "min(zoom+0.0007,1.15)" if zin else "if(eq(on,1),1.15,max(zoom-0.0007,1.0))"
        vf = (f"scale={w * 2}:{h * 2},zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:"
              f"s={w}x{h}:fps={FPS},{GRADE},format=yuv420p")
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(src), "-t", f"{seconds:.2f}", "-vf", vf]
    else:
        vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setpts=1.15*PTS,fps={FPS},"
              f"{GRADE},format=yuv420p")
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", str(src), "-t", f"{seconds:.2f}",
               "-an", "-vf", vf]
    subprocess.run(cmd + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19", str(dst)], check=True)


def xfade_concat(clips, durs, out, fade=0.5):
    if len(clips) == 1:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(clips[0]), "-c", "copy", str(out)], check=True)
        return
    inputs, fc, off, prev = [], [], 0.0, "[0:v]"
    for c in clips:
        inputs += ["-i", str(c)]
    for i in range(1, len(clips)):
        off += durs[i - 1] - fade
        lab = f"[v{i}]"
        fc.append(f"{prev}[{i}:v]xfade=transition=fade:duration={fade}:offset={off:.3f}{lab}")
        prev = lab
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(fc), "-map", prev,
                    "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", str(out)], check=True)


def ass(subs, path, w, h, size, margin_v, align=2, upper=False):
    def ts(x):
        hh, r = divmod(max(0, x), 3600)
        mm, ss = divmod(r, 60)
        return f"{int(hh)}:{int(mm):02d}:{ss:05.2f}"
    name = "Montserrat" if FONT.exists() else "DejaVu Sans"
    head = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {w}\nPlayResY: {h}\nWrapStyle: 0\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
            "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
            "MarginR, MarginV, Encoding\n"
            f"Style: S,{name},{size},&H00FFFFFF,&H000000FF,&H00101010,&H80000000,1,0,0,0,100,100,0,0,1,4,1,{align},"
            f"90,90,{margin_v},1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    ev = []
    for a, b, t in subs:
        t = t.replace("{", "(").replace("}", ")")
        ev.append(f"Dialogue: 0,{ts(a)},{ts(b)},S,,0,0,0,,{t.upper() if upper else t}")
    path.write_text(head + "\n".join(ev) + "\n", encoding="utf-8")


CAP_FONT = ROOT / "assets" / "fonts" / "Poppins-ExtraBold.ttf"
_WHISPER = None


def _norm(w):
    return re.sub(r"[^a-z0-9]", "", w.lower())


def word_times(audio, subs):
    """Zeit für jedes Wort des Skripts: Whisper hört die Sprachspur ab, die Wörter werden dem Skript zugeordnet.
    Ohne Whisper: Schätzung nach Wortlänge innerhalb jedes Satzes."""
    words = []                                            # (wort, satz_start, satz_ende, anteil_start, anteil_ende)
    for a, b, txt in subs:
        ws = txt.split()
        lens = np.cumsum([0] + [len(w) + 2 + (4 if w[-1:] in ",;:" else 0) for w in ws])
        for k, w in enumerate(ws):
            words.append([w, a + (b - a) * lens[k] / lens[-1], a + (b - a) * lens[k + 1] / lens[-1]])
    global _WHISPER
    try:
        import difflib
        from faster_whisper import WhisperModel
        if _WHISPER is None:
            _WHISPER = WhisperModel("small.en", device="cpu", compute_type="int8")
        a16 = resample_poly(audio, 16000, SR).astype(np.float32)
        segs, _ = _WHISPER.transcribe(a16, language="en", word_timestamps=True, beam_size=1,
                                      initial_prompt=" ".join(t for _, _, t in subs)[:800])
        heard = [(w.word, w.start, w.end) for s in segs for w in (s.words or [])]
        sm = difflib.SequenceMatcher(None, [_norm(w[0]) for w in words], [_norm(h[0]) for h in heard], autojunk=False)
        hit = 0
        for blk in sm.get_matching_blocks():
            for j in range(blk.size):
                words[blk.a + j][1], words[blk.a + j][2] = heard[blk.b + j][1], heard[blk.b + j][2]
                hit += 1
        print(f"  Wort-Timing: {hit}/{len(words)} Wörter per Whisper erkannt")
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ Whisper nicht verfügbar ({e}) – Wortzeiten geschätzt")
    for k in range(1, len(words)):                         # Reihenfolge absichern
        words[k][1] = max(words[k][1], words[k - 1][1] + 0.02)
        words[k][2] = max(words[k][2], words[k][1] + 0.08)
    return [tuple(w) for w in words]


def karaoke_ass(words, path, w, h, size, margin_v, align=2, upper=False, per=3):
    """Wenige Wörter auf einmal, das gesprochene Wort leuchtet gelb auf und wird kurz größer."""
    def ts(x):
        hh, r = divmod(max(0, x), 3600)
        mm, ss = divmod(r, 60)
        return f"{int(hh)}:{int(mm):02d}:{ss:05.2f}"
    name = "Poppins ExtraBold" if CAP_FONT.exists() else ("Montserrat" if FONT.exists() else "DejaVu Sans")
    head = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {w}\nPlayResY: {h}\nWrapStyle: 2\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
            "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
            "MarginR, MarginV, Encoding\n"
            f"Style: K,{name},{size},&H00FFFFFF,&H000000FF,&H00000000,&H96000000,0,0,0,0,100,100,1,0,1,"
            f"{max(3, size // 14)},{max(2, size // 22)},{align},60,60,{margin_v},1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    groups, cur = [], []
    for wd in words:                                       # Gruppen: max. `per` Wörter, Bruch nach Satzzeichen/Pausen
        if cur and (len(cur) >= per or cur[-1][0][-1:] in ".,!?;:" or wd[1] - cur[-1][2] > 0.6):
            groups.append(cur)
            cur = []
        cur.append(wd)
    groups += [cur] if cur else []
    ev = []
    for gi, g in enumerate(groups):
        end = min(g[-1][2] + 0.35, groups[gi + 1][0][1]) if gi + 1 < len(groups) else g[-1][2] + 0.6
        for k, (wd, a, b) in enumerate(g):
            b2 = g[k + 1][1] if k + 1 < len(g) else end
            parts = []
            for j, (x, _, _) in enumerate(g):
                x = x.replace("{", "(").replace("}", ")")
                x = x.upper() if upper else x
                parts.append("{\\c&H00D7FF&\\fscx112\\fscy112}" + x + "{\\c&HFFFFFF&\\fscx100\\fscy100}" if j == k else x)
            pop = "{\\fad(60,0)}" if k == 0 else ""
            ev.append(f"Dialogue: 0,{ts(a)},{ts(b2)},K,,0,0,0,,{pop}{' '.join(parts)}")
    path.write_text(head + "\n".join(ev) + "\n", encoding="utf-8")


def music_bed(seconds, work):
    import fetch_sounds as fsd
    key = os.environ.get("FREESOUND_API_KEY")
    for q in ["cinematic ambient documentary", "ambient space music", "cinematic pad ambient"]:
        try:
            for s, url in fsd.search(key, q):
                if {"vocal", "vocals", "voice", "singing"} & {t.lower() for t in s.get("tags", [])}:
                    continue
                raw = work / "music.ogg"
                raw.write_bytes(requests.get(url, timeout=120).content)
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", str(raw), "-t",
                                f"{seconds}", "-ac", "2", "-ar", str(SR), str(work / "music.wav")], check=True)
                _, a = wavfile.read(work / "music.wav")
                return a.astype(np.float32) / 32768
        except Exception:  # noqa: BLE001
            continue
    return np.zeros((int(seconds * SR), 2), np.float32)


def mix_and_render(video, voice_audio, out, work, subs_ass, music_db=-24):
    total = len(voice_audio) / SR
    mus = music_bed(total + 1, work)[: len(voice_audio)]
    env = np.convolve((np.abs(voice_audio) > 0.01).astype(np.float32), np.ones(SR // 4) / (SR // 4), "same")
    mus = mus * (10 ** (music_db / 20)) * (1 - 0.5 * np.clip(env * 3, 0, 1))[:, None]
    f = min(len(mus), 3 * SR)
    mus[-f:] *= np.linspace(1, 0, f)[:, None]
    mix = voice_audio[:, None] + mus
    mix = np.clip(mix / max(1.0, np.max(np.abs(mix)) / 0.95), -1, 1)
    wavfile.write(work / "mix.wav", SR, (mix * 32767).astype(np.int16))
    fdir = (ROOT / "assets" / "fonts").as_posix()
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", "mix.wav",
                    "-vf", f"subtitles={subs_ass.name}:fontsdir='{fdir}',fade=t=out:st={total - 1.5}:d=1.5",
                    "-map", "0:v", "-map", "1:a", "-t", f"{total:.2f}", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                    "-pix_fmt", "yuv420p", "-af", "highpass=f=70,acompressor=threshold=-20dB:ratio=2.5:makeup=2,"
                    "loudnorm=I=-14:TP=-1.5:LRA=9", "-c:a", "aac", "-b:a", "256k", "-ar", "48000",
                    "-movflags", "+faststart", str(out)], cwd=work, check=True)


BRAND = ROOT / "assets" / "brand" / "whatif"


def brand(main, out, work, starts, total):
    """Hook -> Intro -> 1. Hälfte -> Abo-Einspieler -> 2. Hälfte -> Outro (Clips des Kanals)."""
    intro, abo, outro = (BRAND / f for f in ("intro.mp4", "abo.mp4", "outro.mp4"))
    if not all(x.exists() for x in (intro, abo, outro)) or len(starts) < 3:
        subprocess.run(["cp", str(main), str(out)], check=True)
        return
    hook = float(starts[1])                                   # Ende des ersten Abschnitts (Hook)
    mid = float(min(starts[2:], key=lambda x: abs(x - total / 2)))
    parts = [(main, 0, hook), (intro, None, None), (main, hook, mid), (abo, None, None), (main, mid, total), (outro, None, None)]
    args, flt = [], ""
    for k, (src, a, b) in enumerate(parts):
        args += (["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}"] if a is not None else []) + ["-i", str(src)]
        f = 0.12                                              # kurze Ton-Blenden gegen Knackser an den Schnitten
        dur = (b - a) if a is not None else float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(src)],
            capture_output=True, text=True).stdout)
        flt += (f"[{k}:v]scale=1920:1080,fps=30,format=yuv420p,setsar=1[v{k}];"
                f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,afade=t=in:d={f},"
                f"afade=t=out:st={max(0, dur - f):.3f}:d={f}[a{k}];")
    flt += "".join(f"[v{k}][a{k}]" for k in range(len(parts))) + f"concat=n={len(parts)}:v=1:a=1[v][a]"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args, "-filter_complex", flt, "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-c:a", "aac", "-b:a", "256k",
                    "-movflags", "+faststart", str(out)], check=True)
    print(f"  Intro nach {hook:.0f} s, Abo-Einspieler bei {mid:.0f} s, Outro am Ende")


# ----------------------------------------------------------------- Hauptablauf
def build(out: Path, minutes=9.0, seed=None):
    rnd = random.Random(seed)
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=out))
    print("▶ Thema & Recherche …")
    sc = plan(rnd, minutes)
    segs = sc["segments"]
    print(f"  {sc['question']} → „{sc['title']}“, {len(segs)} Abschnitte, {len(sc['sources'])} Quellen")

    import modal
    from modal_app import ImageFlux, Voice, app, download_flux
    ref_path = ROOT / "data" / "voices" / "anime" / "narrator.wav"
    ref = ref_path.read_bytes() if ref_path.exists() else b""
    import time as _t
    t0 = _t.time()
    with modal.enable_output(), app.run():
        print("▶ Modelle bereitstellen …", flush=True)
        download_flux.remote()
        print(f"  ({_t.time() - t0:.0f} s)", flush=True)
        voice, flux = Voice(), ImageFlux()
        print("▶ Stimme …")
        seg_audio, seg_subs = [], []
        for i, s in enumerate(segs):
            a, subs = narrate(voice, ref, sentences(s["text"]), work, f"s{i}")
            seg_audio.append(np.concatenate([a, np.zeros(int(0.5 * SR), np.float32)]))
            seg_subs.append(subs)
            print(f"  Stimme {i + 1}/{len(segs)} ({_t.time() - t0:.0f} s)", flush=True)
        print("▶ Bilder …")
        sources, used_ids = [], set()
        for i, s in enumerate(segs):
            v = s.get("visual") or {}
            src, is_img = None, False
            if v.get("kind") == "stock" and v.get("query"):
                src = stock_clip(v["query"], work, used_ids)
            if src is None:
                prompt = v.get("prompt") or v.get("query") or s["text"][:200]
                png = flux.generate.remote(f"cinematic photorealistic, dramatic lighting, highly detailed, 16:9. "
                                           f"{prompt}. no text, no watermark", seed=100 + i)
                src = work / f"ai_{i}.png"
                src.write_bytes(png)
                is_img = True
            sources.append((src, is_img))
            print(f"  Bild {i + 1}/{len(segs)} {'KI' if is_img else 'Stock'} ({_t.time() - t0:.0f} s)", flush=True)
        print("▶ Shorts-Stimmen …")
        short_audio = []
        for k, sh in enumerate(sc.get("shorts", [])[:2]):
            short_audio.append(narrate(voice, ref, sentences(sh["text"]), work, f"sh{k}"))

    # ---- langes Video
    print("▶ Schnitt …")
    fade = 0.5
    clips, durs, all_subs, t = [], [], [], 0.0
    for i, ((src, is_img), a, subs) in enumerate(zip(sources, seg_audio, seg_subs)):
        d = len(a) / SR + (fade if i < len(segs) - 1 else 0)
        dst = work / f"seg_{i:02d}.mp4"
        segment_video(src, dst, d, is_img, seed=i)
        clips.append(dst)
        durs.append(d)
        all_subs += [(t + x, t + y, txt) for x, y, txt in subs]
        t += len(a) / SR
    xfade_concat(clips, durs, work / "joined.mp4", fade)
    voice_all = np.concatenate(seg_audio)
    karaoke_ass(word_times(voice_all, all_subs), work / "subs.ass", 1920, 1080, 76, 90)
    mix_and_render(work / "joined.mp4", voice_all, work / "main.mp4", work, work / "subs.ass")
    starts = np.cumsum([0] + [len(a) / SR for a in seg_audio])[:-1]
    brand(work / "main.mp4", out / "video.mp4", work, starts, len(voice_all) / SR)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "3", "-i", str(work / "main.mp4"), "-frames:v", "1",
                    str(out / "thumb_frame.png")], check=True)

    # ---- Shorts
    shorts_meta = []
    for k, (sh, (a, subs)) in enumerate(zip(sc.get("shorts", [])[:2], short_audio)):
        idx = [i for i in sh.get("visuals", []) if isinstance(i, int) and 0 <= i < len(sources)] or [0, 1, 2]
        total = len(a) / SR
        per = total / len(idx) + fade
        sclips = []
        for j, i in enumerate(idx):
            dst = work / f"sh{k}_{j}.mp4"
            segment_video(sources[i][0], dst, per, sources[i][1], w=1080, h=1920, seed=50 + j)
            sclips.append(dst)
        xfade_concat(sclips, [per] * len(sclips), work / f"sh{k}.mp4", fade)
        karaoke_ass(word_times(a, subs), work / f"sh{k}.ass", 1080, 1920, 92, 0, align=5, upper=True)
        mix_and_render(work / f"sh{k}.mp4", a, out / f"short{k + 1}.mp4", work, work / f"sh{k}.ass", music_db=-22)
        shorts_meta.append({"title": sh.get("title", sc["title"])[:100], "text": sh["text"]})

    src_lines = "\n".join(f"- {tt or url}: {url}" for tt, url in sc["sources"])
    meta = {"question": sc["question"], "title": sc["title"][:100], "description": sc.get("description", ""),
            "tags": sc.get("tags", [])[:20], "sources": sc["sources"], "shorts": shorts_meta,
            "minutes": round(len(voice_all) / SR / 60, 1),
            "full_description": (f"{sc.get('description', '')}\n\nSources & further reading:\n{src_lines}\n\n"
                                 "Some scenes are AI-generated illustrations of hypothetical scenarios.\n\n"
                                 "#whatif #science #space #beyondtheif")}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    subprocess.run(["rm", "-rf", str(work)])
    print(f"  ✓ {meta['title']} ({meta['minutes']} Min.) + {len(shorts_meta)} Shorts")
    return meta


def upload_all(out: Path, meta):
    import upload
    token = os.environ.get(CFG["token_secret"])
    if not token:
        raise SystemExit(f"Secret {CFG['token_secret']} fehlt.")
    yt = upload.service(token)
    upload.check_channel(yt, CFG)
    ch = {"category_id": CFG.get("category_id", "28"), "made_for_kids": False, "privacy": "public",
          "language": "en", "name": CFG["name"], "token_secret": CFG["token_secret"]}
    m = {"title": meta["title"], "description": meta["full_description"], "tags": meta["tags"]}
    vid = upload.upload(yt, out / "video.mp4", m, ch)
    try:
        upload.set_thumbnail(yt, vid, out / "thumb_frame.png")
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ Thumbnail: {e}")
    try:
        pid = upload.ensure_playlist(yt, "whatif", "What If…? Science Scenarios", "Science-based what-if scenarios.")
        upload.add_to_playlist(yt, vid, pid)
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ Playlist: {e}")
    print(f"  ✓ https://youtu.be/{vid}")
    for k, sm in enumerate(meta["shorts"]):
        sv = upload.upload(yt, out / f"short{k + 1}.mp4",
                           {"title": sm["title"], "description": sm["text"] + f"\n\nFull video: https://youtu.be/{vid}\n#shorts #whatif",
                            "tags": ["shorts", "whatif", "science"]}, ch)
        print(f"  ✓ Short: https://youtu.be/{sv}")
    u = used()
    u.append(meta["question"])
    USED.write_text(json.dumps(u[-300:], ensure_ascii=False, indent=1), encoding="utf-8")
    upload.mark_uploaded("whatif")


# ----------------------------------------------------------------- Tages-Short zu aktuellen News (Algorithmus-Test)
NEWS_TASK = """You run "Beyond the If" (science what-if scenarios). Here are today's top science/tech headlines:
{news}
Pick the ONE headline with the most viral what-if potential and turn it into a YouTube Short / Instagram Reel.
Facts you may use (Wikipedia): {facts}
Rules: 70–90 words, first sentence is a scroll-stopping hook that references the real news briefly,
then the what-if scenario with real science, end with a question to the viewer + "Follow for more what-ifs."
No invented numbers, no fear-mongering, no real private people. Visuals: 4 scenes (stock or ai, like before).
Answer ONLY JSON: {{"headline": "...", "question": "What if ...?", "title": "max 80 chars incl #shorts",
 "text": "...", "visuals": [{{"kind": "stock|ai", "query": "...", "prompt": "..."}}], "hashtags": ["..."]}}"""


def perf_hint():
    """Lernschleife: welche Themen liefen bisher am besten (aus data/stats)?"""
    import glob
    best = []
    for f in sorted(glob.glob(str(ROOT / "data" / "stats" / "*.json")))[-3:]:
        try:
            for ch in json.loads(Path(f).read_text(encoding="utf-8"))["channels"]:
                if ch["name"] == CFG["name"]:
                    best += [(r["views"], r["title"]) for r in ch["list"]]
        except Exception:  # noqa: BLE001
            pass
    best = sorted(set(best), reverse=True)[:5]
    return "\n".join(f"- {t} ({v} views)" for v, t in best) or "no data yet"


def news_short(out: Path, seed=None):
    rnd = random.Random(seed)
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=out))
    news = []
    for q in ["science", "space NASA", "physics", "climate", "AI technology", "medicine discovery"]:
        news += google_news(q + " when:2d", 5)
    news_txt = "\n".join(f"- {t}" for t, _ in news[:25])
    sc = gemini.ask_json(NEWS_TASK.format(news=news_txt, facts="(see below)") +
                         f"\nBest performing videos so far (prefer similar topics/hooks):\n{perf_hint()}", temperature=0.9)
    wiki = wikipedia(re.sub(r"(?i)^what if\s+", "", sc.get("question", "")).rstrip("?"))
    if wiki:                                                    # Faktencheck-Durchgang mit Wikipedia
        sc = gemini.ask_json("Check this Short script against these facts and fix anything inaccurate; keep length, "
                             "tone and JSON format exactly.\nFacts:\n" +
                             "\n".join(f"[{t}] {x[:1200]}" for t, x, _ in wiki) + "\n\nScript JSON:\n" +
                             json.dumps(sc, ensure_ascii=False), temperature=0.3) | {"_checked": True}
    print(f"  News: {sc.get('headline')}\n  → {sc.get('question')}")
    import modal
    from modal_app import ImageFlux, Voice, app, download_flux
    ref_path = ROOT / "data" / "voices" / "anime" / "narrator.wav"
    ref = ref_path.read_bytes() if ref_path.exists() else b""
    with modal.enable_output(), app.run():
        download_flux.remote()
        voice, img = Voice(), ImageFlux()
        a, subs = narrate(voice, ref, sentences(sc["text"]), work, "n")
        srcs, used_ids = [], set()
        for i, v in enumerate((sc.get("visuals") or [])[:5]):
            src, is_img = None, False
            if v.get("kind") == "stock" and v.get("query"):
                src = stock_clip(v["query"], work, used_ids)
            if src is None:
                png = img.generate.remote(f"cinematic photorealistic, dramatic lighting, highly detailed, vertical "
                                          f"composition. {v.get('prompt') or v.get('query')}. no text", seed=200 + i,
                                          width=928, height=1664)
                src = work / f"ai_{i}.png"
                src.write_bytes(png)
                is_img = True
            srcs.append((src, is_img))
    fade, total = 0.5, len(a) / SR
    per = total / max(1, len(srcs)) + fade
    clips = []
    for j, (src, is_img) in enumerate(srcs):
        dst = work / f"c{j}.mp4"
        segment_video(src, dst, per, is_img, w=1080, h=1920, seed=j)
        clips.append(dst)
    xfade_concat(clips, [per] * len(clips), work / "short.mp4", fade)
    karaoke_ass(word_times(a, subs), work / "s.ass", 1080, 1920, 92, 0, align=5, upper=True)
    mix_and_render(work / "short.mp4", a, out / "news_short.mp4", work, work / "s.ass", music_db=-22)
    src_lines = "\n".join(f"- {t}: {u}" for t, _, u in wiki if u)
    meta = {"title": sc["title"][:100], "question": sc.get("question"), "headline": sc.get("headline"),
            "description": f"{sc['text']}\n\nBased on today's news: {sc.get('headline')}\nBackground:\n{src_lines}\n\n"
                           "Some scenes are AI-generated illustrations.\n" + " ".join("#" + h.lstrip("#") for h in sc.get("hashtags", [])[:6]),
            "tags": [h.lstrip("#") for h in sc.get("hashtags", [])][:15] + ["shorts", "whatif"]}
    (out / "news_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    subprocess.run(["rm", "-rf", str(work)])
    return meta


def upload_news_short(out: Path, meta):
    import upload
    yt = upload.service(os.environ[CFG["token_secret"]])
    upload.check_channel(yt, CFG)
    ch = {"category_id": CFG.get("category_id", "28"), "made_for_kids": False, "privacy": "public", "name": CFG["name"]}
    vid = upload.upload(yt, out / "news_short.mp4", meta, ch)
    print(f"  ✓ Short: https://youtu.be/{vid}")
    if os.environ.get("IG_TOKEN_WHATIF"):
        import ig_queue
        ig_queue.add("whatif", out / "news_short.mp4", meta["description"][:2000])
    upload.mark_uploaded("whatif-news")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output/whatif")
    ap.add_argument("--minutes", type=float, default=9)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--news-short", action="store_true", help="nur ein Short zu aktuellen News")
    a = ap.parse_args()
    if a.news_short:
        if not a.dry_run:
            import upload
            if os.environ.get("FORCE_UPLOAD") != "1" and upload.uploaded_today("whatif-news"):
                sys.exit("Heute schon gepostet – übersprungen.")
        m = news_short(Path(a.out))
        if not a.dry_run:
            upload_news_short(Path(a.out), m)
        sys.exit(0)
    if not a.dry_run:
        import upload
        if os.environ.get("FORCE_UPLOAD") != "1" and upload.uploaded_today("whatif"):
            sys.exit("Heute schon hochgeladen – übersprungen.")
    meta = build(Path(a.out), a.minutes)
    if not a.dry_run:
        upload_all(Path(a.out), meta)
