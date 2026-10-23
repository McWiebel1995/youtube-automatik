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
VW, VH = 1080, 608                     # 16:9-Videofenster im Short (90er-Anime-Reel-Format)
VY = 700                               # Oberkante des Videofensters; darüber steht die Schlagzeile
END_CARD = "Fictional story inspired by real events."
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
_ANTON = HERE.parent / "assets" / "fonts" / "Anton.ttf"
HEAD_FONT = str(_ANTON) if _ANTON.exists() else FONT


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
SAFE_NEG = "nsfw, cleavage, fanservice, suggestive, revealing clothes, underwear, large breasts"


def cast_tags(ids, chars, action=""):
    """Animagine ist Tag-basiert: ohne klare Personen-Tags malt es gern Mädchen. Daher explizit."""
    g = [profile_of(chars[c])["gender"] for c in ids if c in chars]
    m, f = g.count("male"), g.count("female")
    tags = []
    if m:
        tags.append("1boy" if m == 1 else f"{min(m, 6)}boys")
    if f:
        tags.append("1girl" if f == 1 else f"{min(f, 6)}girls")
    if m and not f:
        tags.append("male focus")
    ages = [(profile_of(chars[c])["gender"], (chars[c].get("voice_profile") or {}).get("age")) for c in ids if c in chars]
    for gen, age in ages[:2]:
        if age == "adult":
            tags.append("mature male, 30s" if gen == "male" else "mature female")
        elif age == "old":
            tags.append("old man" if gen == "male" else "old woman")
    if not g:
        crowd = any(w in action.lower() for w in ["crowd", "people", "riot", "rioters", "citizens", "police"])
        tags.append("crowd, multiple boys, scenery" if crowd else "no humans, scenery")
    neg = SAFE_NEG + ("" if f else ", 1girl, female, woman")
    return ", ".join(tags), neg


FRANCHISE = {"super saiyan": "golden", "saiyan": "golden", "kamehameha": "energy blast", "spirit bomb": "energy sphere",
             "dragon ball": "90s action anime", "goku": "hero", "naruto": "ninja", "rasengan": "spinning energy orb",
             "one piece": "pirate", "sailor moon": "magical", "jojo": "", "gundam": "mecha", "evangelion": "mecha"}


def clean(text):
    t = text or ""
    for k, v in FRANCHISE.items():
        t = re.sub(re.escape(k) + r"(-style| style)?", v, t, flags=re.I)
    return t


def gpu_shots(vid, sc, work, no_gpu=False):
    shots = sc["shots"]
    style = (sc.get("setting") or {}).get("art_style", "cinematic anime")
    base = int(hashlib.sha1(vid.encode()).hexdigest()[:8], 16)
    notes, t0 = [], time.time()
    if no_gpu:                                   # Test ohne GPU: farbige Platzhalter-Clips
        for s in shots:
            out = work / f"clip_{s['n']:02d}.mp4"
            sh("ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
               f"color=c=0x{(s['n'] * 2654435761) % 0xFFFFFF:06x}:s=832x480:d=3:r=24",
               "-vf", f"drawtext=fontfile={FONT}:text='Shot {s['n']}':fontsize=60:fontcolor=white:x=(w-tw)/2:y=(h-th)/2",
               "-pix_fmt", "yuv420p", out)
            sh("ffmpeg", "-y", "-loglevel", "error", "-i", out, "-frames:v", "1", work / f"key_{s['n']:02d}.png")
        return {"notes": ["Testlauf ohne GPU"], "gpu_seconds": 0}

    if os.environ.get("ANIME_ENGINE", "v2") == "v2":
        return gpu_shots_v2(vid, sc, work, style, base, notes, t0)

    import modal
    from modal_app import Studio, app
    chars = {c.get("id"): c for c in sc.get("characters", [])}
    with modal.enable_output(), app.run():
        studio = Studio()
        # Referenzbild pro Figur – daran werden alle Shots ausgerichtet (gleiches Aussehen)
        refs = {}
        for j, (cid, c) in enumerate(chars.items()):
            status(vid, state="running", progress=f"Figur {j + 1}/{len(chars)}")
            tags, neg = cast_tags([cid], chars)
            res = studio.keyframe.remote(
                f"{tags}, solo, full body, front view, standing, dark city street at night background. "
                f"{style}. {c.get('design_sheet', '')}"[:1800],
                negative=neg, seed=base + 7 + j, width=832, height=1216)
            refs[cid] = res["png"]
            (work / f"ref_{cid}.png").write_bytes(res["png"])
            if res.get("note"):
                notes.append(res["note"])
        for i, s in enumerate(shots):
            status(vid, state="running", progress=f"Bild {i + 1}/{len(shots)}")
            who = [c for c in (s.get("characters") or []) if c in refs] or \
                  [d.get("character") for d in (s.get("dialogue") or []) if d.get("character") in refs]
            tags, neg = cast_tags(who, chars, s.get("action", ""))
            prompt = clean(f"{tags}. {style}. {s.get('image_prompt', '')}. wide 16:9 anime frame")
            ref = refs.get(who[0]) if who else b""
            res = studio.keyframe.remote(prompt[:1800], negative=neg, seed=base + s["n"], ref_png=ref or b"",
                                         ref_scale=0.25 if len(who) > 1 else 0.35)
            png = res["png"]
            (work / f"key_{s['n']:02d}.png").write_bytes(png)
            status(vid, state="running", progress=f"Animation {i + 1}/{len(shots)}")
            motion = clean(f"{s.get('motion_prompt', '')}. {s.get('action', '')}. {s.get('camera', '')}")
            dur = min(4.0, max(2.0, float(s.get("duration_s") or 3)))
            frames = int(dur * 24) // 4 * 4 + 1
            res = studio.animate.remote(png, motion[:1800], num_frames=frames, seed=base + 100 + s["n"])
            (work / f"clip_{s['n']:02d}.mp4").write_bytes(res["mp4"])
            if res.get("note"):
                notes.append(f"Shot {s['n']}: {res['note']}")
            if res.get("mode") == "t2v":
                notes.append(f"Shot {s['n']}: ohne Startbild animiert (Figur evtl. weniger konsistent)")
    return {"notes": sorted(set(notes)), "gpu_seconds": round(time.time() - t0)}


def gpu_shots_v2(vid, sc, work, style, base, notes, t0):
    """V2: Referenzbild je Figur (Animagine, 90er-Look) -> Szenenbild mit Qwen-Image-Edit (Figur bleibt gleich)
    -> Animation mit Wan 2.2 I2V 14B. Shots mit "continues_previous" starten mit dem letzten Bild des Vorgängers."""
    import modal
    from modal_app import AnimateV2, KeyframeV2, Studio, app, download_v2
    shots = sc["shots"]
    chars = {c.get("id"): c for c in sc.get("characters", [])}
    with modal.enable_output(), app.run():
        status(vid, state="running", progress="Modelle bereitstellen")
        download_v2.remote()                      # einmalig, danach sofort fertig (liegt im Volume)
        studio = Studio()
        refs = {}
        for j, (cid, c) in enumerate(chars.items()):
            status(vid, state="running", progress=f"Figur {j + 1}/{len(chars)}")
            tags, neg = cast_tags([cid], chars)
            res = studio.keyframe.remote(
                f"{tags}, solo, full body, front view, standing, simple background, character sheet. "
                f"{c.get('design_sheet', '')}. {style}"[:1800], negative=neg, seed=base + 7 + j, width=832, height=1216)
            refs[cid] = res["png"]
            (work / f"ref_{cid}.png").write_bytes(res["png"])
        kf = KeyframeV2()
        keys = {}
        for i, s in enumerate(shots):
            if s.get("continues_previous") and i > 0:
                continue
            status(vid, state="running", progress=f"Bild {i + 1}/{len(shots)}")
            who = [c for c in (s.get("characters") or []) if c in refs] or \
                  [d.get("character") for d in (s.get("dialogue") or []) if d.get("character") in refs]
            names = ", ".join(chars[c].get("name", c) for c in who[:3])
            prompt = clean(f"1990s retro anime screencap, cel shading, film grain, wide 16:9 frame. "
                           f"{'Keep the EXACT same character(s) as in the reference image(s): same face, hairstyle, hair color and outfit (' + names + '). ' if who else ''}"
                           f"{' '.join(chars[c].get('design_sheet', '')[:220] for c in who[:2])} "
                           f"{s.get('image_prompt', '')}. {style}")
            if who:
                res = kf.edit.remote([refs[c] for c in who[:3]], prompt[:1800], seed=base + s["n"])
                keys[s["n"]] = res["png"]
            else:                                 # Szene ohne Hauptfigur: normales Bild
                tags, neg = cast_tags([], chars, s.get("action", ""))
                keys[s["n"]] = studio.keyframe.remote(f"{tags}. {prompt}"[:1800], negative=neg, seed=base + s["n"])["png"]
            (work / f"key_{s['n']:02d}.png").write_bytes(keys[s["n"]])
        anim = AnimateV2()
        last = None
        for i, s in enumerate(shots):
            status(vid, state="running", progress=f"Animation {i + 1}/{len(shots)}")
            start = last if (s.get("continues_previous") and last) else keys.get(s["n"]) or last
            motion = clean(f"{s.get('motion_prompt', '')}. {s.get('action', '')}. {s.get('camera', '')}")
            dur = min(4.0, max(2.0, float(s.get("duration_s") or 3)))
            res = anim.animate.remote(start, motion[:1800], num_frames=int(dur * 16) // 4 * 4 + 1, seed=base + 100 + s["n"])
            (work / f"clip_{s['n']:02d}.mp4").write_bytes(res["mp4"])
            last = res["last_png"]
    notes.append("Engine V2: Qwen-Image-Edit + Wan 2.2 14B")
    return {"notes": sorted(set(notes)), "gpu_seconds": round(time.time() - t0)}


# ----------------------------------------------------------------- 3 STIMMEN
_tts = {}


KOKORO_VOICES = {   # (Geschlecht, Tonlage) -> Kandidaten; jede Figur bekommt eine eigene
    ("male", "low"): ["am_onyx", "bm_george", "am_fenrir", "am_michael"],
    ("male", "mid"): ["am_michael", "am_eric", "bm_lewis", "am_adam", "am_fenrir"],
    ("male", "high"): ["am_puck", "am_liam", "am_echo", "bm_daniel"],
    ("female", "low"): ["af_nicole", "bf_isabella", "af_sarah", "af_heart"],
    ("female", "mid"): ["af_heart", "af_sarah", "bf_emma", "af_nova"],
    ("female", "high"): ["af_bella", "af_sky", "af_jessica", "af_nova"],
}
EMOTION = {   # Chatterbox: (exaggeration, cfg_weight, Lautstärke dB)
    "shout": (1.05, 0.3, 2), "angry": (0.85, 0.35, 1), "mocking": (0.75, 0.4, 0), "determined": (0.7, 0.4, 0),
    "crying": (0.8, 0.35, -1), "fearful": (0.7, 0.4, -1), "calm": (0.45, 0.5, -1), "whisper": (0.35, 0.5, -6),
}
REF_TEXT = ("I have waited a long time for this moment. Whatever happens tonight, "
            "I will not run away again. Not this time.")


def profile_of(char):
    p = dict(char.get("voice_profile") or {})
    desc = f"{char.get('voice', '')} {char.get('role', '')} {char.get('design_sheet', '')}".lower()
    if p.get("gender") not in ("male", "female"):
        p["gender"] = "female" if any(w in desc for w in ["female", "woman", "girl", "she ", "her ", "lady"]) else "male"
    if p.get("pitch") not in ("low", "mid", "high"):
        p["pitch"] = ("low" if any(w in desc for w in ["deep", "gravel", "old", "low"]) else
                      "high" if any(w in desc for w in ["teen", "young", "boy", "girl", "bright"]) else "mid")
    return p


def assign_voices(characters):
    """Jede Figur bekommt eine andere Kokoro-Grundstimme (Klangfarbe) + eigene Tonhöhen-Nuance."""
    used, out = set(), {}
    for i, c in enumerate(characters):
        p = profile_of(c)
        pool = KOKORO_VOICES[(p["gender"], p["pitch"])]
        v = next((x for x in pool if x not in used), pool[i % len(pool)])
        used.add(v)
        out[c.get("id")] = v
    return out


def voice_for(char):   # Fallback, falls eine Figur fehlt
    return "af_heart" if profile_of(char or {})["gender"] == "female" else "am_michael"


def dub_fx(a, emotion):
    """Sauberer Studio-Klang: nur Pegel angleichen; bei Schreien ein Hauch Raum (kein Telefon-/Schrank-Filter)."""
    a = a.astype(np.float32)
    if emotion == "shout":
        ir = np.zeros(int(0.12 * SR), np.float32)
        ir[0] = 1.0
        for k, d in enumerate([0.019, 0.037, 0.061]):
            ir[int(d * SR)] = 0.18 * 0.55 ** k
        a = np.convolve(a, ir)[: len(a) + int(0.1 * SR)].astype(np.float32)
    peak = np.max(np.abs(a)) or 1.0
    return (a / peak * 0.9).astype(np.float32)


def voice_chain(vo, work):
    """Broadcast-Kette für Sprache: Trittschall weg, etwas Präsenz, Zischlaute zähmen, sanft komprimieren."""
    src, dst = work / "vo_raw.wav", work / "vo_proc.wav"
    wavfile.write(src, SR, (np.clip(vo, -1, 1) * 32767).astype(np.int16))
    try:
        sh("ffmpeg", "-y", "-loglevel", "error", "-i", src, "-af",
           "highpass=f=80,equalizer=f=250:t=q:w=1.2:g=-2,equalizer=f=3800:t=q:w=1:g=2.5,deesser=i=0.4,"
           "acompressor=threshold=-20dB:ratio=3:attack=6:release=90:makeup=3,alimiter=limit=0.95", dst)
        _, x = wavfile.read(dst)
        x = x.astype(np.float32) / 32768
        return x[: len(vo)] if len(x) >= len(vo) else np.pad(x, (0, len(vo) - len(x)))
    except Exception:  # noqa: BLE001
        return vo


def fade(x, n, out=False):
    n = min(n, len(x))
    if n <= 0:
        return x
    r = np.linspace(1, 0, n) if out else np.linspace(0, 1, n)
    if x.ndim == 2:
        r = r[:, None]
    if out:
        x[-n:] *= r
    else:
        x[:n] *= r
    return x


def tts(text, voice, out):
    """Kokoro (Apache 2.0). Fallback: espeak-ng. Gibt Mono-Array mit SR zurück."""
    try:
        from kokoro import KPipeline
        if "p" not in _tts:
            _tts["p"] = KPipeline(lang_code="a")
        chunks = [a for _, _, a in _tts["p"](text, voice=voice, speed=1.0)]
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
            "fields": "id,name,previews,duration,tags"})
        r.raise_for_status()
        bad = {"vocal", "vocals", "voice", "singing", "speech", "talking", "lyrics", "rap", "choir"}
        res = [x for x in r.json().get("results", []) if not bad & {t.lower() for t in x.get("tags", [])}]
        if not res:
            cache[query] = None
            return None
        pv = res[0]["previews"]
        url = pv.get("preview-hq-ogg") or pv.get("preview-hq-mp3")
        raw = work / f"fs_{res[0]['id']}.ogg"
        raw.write_bytes(requests.get(url, timeout=60).content)
        wav = raw.with_suffix(".wav")
        sh("ffmpeg", "-y", "-loglevel", "error", "-i", raw, "-ac", "2", "-ar", SR, wav)
        _, a = wavfile.read(wav)
        a = a.astype(np.float32) / 32768
        cache[query] = a if a.ndim == 2 else np.stack([a, a], 1)
    except Exception:  # noqa: BLE001
        cache[query] = None
    return cache[query]


BEAT_MUSIC = {     # Beat -> (Freesound-Suche, Lautstärke dB)
    "HOOK": ("dark tense cinematic suspense", -16),
    "EINSTIEG": ("emotional cinematic piano strings", -18),
    "KONFLIKT": ("intense action drums cinematic", -14),
    "WENDEPUNKT": ("suspense drone heartbeat", -21),
    "HÖHEPUNKT": ("epic orchestral battle trailer", -12),
    "NACHHALL": ("sad emotional piano ambient", -18),
}


def score(shots, starts, total, work, cache):
    """Musik in Abschnitten: aufeinanderfolgende Shots mit gleichem Beat bekommen ein passendes Stück,
    weiche Überblendungen dazwischen, kurzer Ton-Abriss direkt vor dem Höhepunkt."""
    n = int(total * SR) + SR
    bed = np.zeros((n, 2), np.float32)
    groups = []
    for s, st in zip(shots, starts):
        beat = (s.get("beat") or "KONFLIKT").upper().replace("HOEHEPUNKT", "HÖHEPUNKT")
        end = st + float(s.get("duration_s") or 3)
        if groups and groups[-1][0] == beat:
            groups[-1][2] = end
        else:
            groups.append([beat, st, end, s.get("music") or ""])
    got = False
    xf = int(0.8 * SR)
    for i, (beat, st, end, cue) in enumerate(groups):
        q, gain = BEAT_MUSIC.get(beat, BEAT_MUSIC["KONFLIKT"])
        track = None
        cue_q = " ".join(w for w in cue.lower().replace(",", " ").split() if w.isalpha())[:60]
        for query in ([f"{cue_q} music"] if cue_q else []) + [f"{q} music", q, "cinematic tension drone"]:
            track = freesound(query, "[20 TO 400]", work, cache)
            if track is not None:
                break
        if track is None:
            continue
        got = True
        a0 = int(max(0, st - (0.8 if i else 0)) * SR)
        a1 = min(n, int((end + 0.8) * SR))
        need = a1 - a0
        off = (len(track) // 5) if len(track) > need * 1.5 else 0          # nicht immer beim leisen Anfang
        reps = int(np.ceil((need + off) / len(track))) + 1
        seg = np.tile(track, (reps, 1))[off: off + need].copy() * (10 ** (gain / 20))
        f = min(xf, len(seg) // 3)
        fade(seg, f)
        fade(seg, f, out=True)
        bed[a0:a0 + len(seg)] += seg
        if beat == "HÖHEPUNKT" and st > 1:                                  # Stille vor dem Impact
            g0, g1 = int((st - 0.7) * SR), int(st * SR)
            bed[g0:g1] *= np.linspace(1, 0.05, g1 - g0)[:, None]
    return bed if got else None


def place(track, clip, start_s, gain_db=0.0):
    i = int(start_s * SR)
    if i >= len(track) or clip is None or not len(clip):
        return
    e = min(len(track), i + len(clip))
    c = clip[: e - i]
    if track.ndim == 2 and c.ndim == 1:
        c = c[:, None]
    elif track.ndim == 1 and c.ndim == 2:
        c = c.mean(axis=1)
    track[i:e] += c * (10 ** (gain_db / 20))


# ----------------------------------------------------------------- 5 SCHNITT
def ass_time(t):
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def render_lines(vid, jobs, chars, kvoice, work, no_gpu, notes):
    """Gibt pro Shot eine Liste von Mono-Arrays (SR) zurück."""
    def kokoro(cid, text):
        return tts(text, kvoice.get(cid) or voice_for(chars.get(cid)), work / "tts.wav")

    if no_gpu:
        notes.add(f"Stimmen: {_tts.get('engine', 'Kokoro')} (ohne GPU)")
        return [[kokoro(c, t) for c, t, _ in lines] for _, lines in jobs]
    try:
        import io as _io

        import modal
        from modal_app import Voice, app
        refs = {}
        for cid in {c for _, lines in jobs for c, _, _ in lines}:
            a = kokoro(cid, REF_TEXT)
            buf = _io.BytesIO()
            wavfile.write(buf, SR, (np.clip(a, -1, 1) * 32767).astype(np.int16))
            refs[cid] = buf.getvalue()
        base = int(hashlib.sha1(vid.encode()).hexdigest()[:6], 16)
        out = []
        with modal.enable_output(), app.run():
            v = Voice()
            for i, (_, lines) in enumerate(jobs):
                shot = []
                for j, (cid, text, emo) in enumerate(lines):
                    ex, cfg, _ = EMOTION.get(emo, EMOTION["determined"])
                    wav = v.speak.remote(text, refs[cid], exaggeration=ex, cfg_weight=cfg, seed=base + i * 10 + j)
                    sr, a = wavfile.read(_io.BytesIO(wav))
                    a = a.astype(np.float32) / (32768 if a.dtype == np.int16 else 1)
                    shot.append(resample_poly(a, SR, sr).astype(np.float32))
                out.append(shot)
        notes.add("Stimmen: Chatterbox (eigene Stimme pro Figur, Emotion pro Zeile)")
        return out
    except Exception as e:  # noqa: BLE001
        notes.add(f"Stimmen: Kokoro-Fallback (Chatterbox-Fehler: {repr(e)[:160]})")
        return [[kokoro(c, t) for c, t, _ in lines] for _, lines in jobs]


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

    # Stimmen: pro Figur eigene Stimme, pro Zeile eigene Emotion (Chatterbox auf Modal, Fallback Kokoro)
    status(vid, state="running", progress="Synchronstimmen")
    vo = np.zeros(int(total * SR) + SR, np.float32)
    subs, voice_notes = [], set()
    kvoice = assign_voices(sc.get("characters") or [])
    jobs = []
    for s, st in zip(shots, starts):
        lines = [(d.get("character"), d.get("line"), (d.get("emotion") or "determined").lower())
                 for d in (s.get("dialogue") or [])]
        if s.get("voiceover"):
            lines.append((main_char.get("id"), s["voiceover"], "calm"))
        jobs.append((st, [x for x in lines if x[1]]))
    rendered = render_lines(vid, jobs, chars, kvoice, work, no_gpu, voice_notes)
    last_end = 0.0
    for (st, lines), audios in zip(jobs, rendered):
        cur = max(st + 0.25, last_end)            # nie zwei Sätze übereinander
        for (cid, text, emo), a in zip(lines, audios):
            a = dub_fx(a, emo) * (10 ** (EMOTION.get(emo, EMOTION["determined"])[2] / 20))
            place(vo, a, cur)
            if subs and subs[-1][1] > cur:
                subs[-1] = (subs[-1][0], cur - 0.02, subs[-1][2])
            subs.append((cur, cur + len(a) / SR + 0.15, text))
            cur += len(a) / SR + 0.15
        last_end = cur

    # Geräusche + Musik – pro Szene passend zur Stimmung (Beat des Drehbuchs)
    cache = {}
    sfx = np.zeros((len(vo), 2), np.float32)
    for s, st in zip(shots, starts):
        dur = float(s.get("duration_s") or 3)
        for k, q in enumerate((s.get("sfx") or [])[:2]):
            clip = freesound(q, "[0.3 TO 12]", work, cache)
            if clip is not None:
                clip = fade(clip[: int((dur + 0.5) * SR)].copy(), int(0.3 * SR), out=True)
                place(sfx, clip, st + 0.15 + 0.6 * k, -4 if k == 0 else -9)
    bed = score(shots, starts, total, work, cache)
    if bed is not None:
        env = np.convolve((np.abs(vo) > 0.01).astype(np.float32), np.ones(SR // 4) / (SR // 4), "same")
        bed *= (1 - 0.55 * np.clip(env * 3, 0, 1))[:, None]              # leiser, wenn gesprochen wird
        fade(bed, len(bed) - int((total - 2) * SR), out=True)
        music = bed
    else:
        bed, music = np.zeros((len(vo), 2), np.float32), None
    vo = voice_chain(vo, work)
    mix = vo[:, None] * 1.0 + sfx + bed                                    # Stimme Mitte, Musik/Geräusche stereo
    mix = np.clip(mix / max(1.0, np.max(np.abs(mix)) / 0.95), -1, 1)
    wavfile.write(work / "mix.wav", SR, (mix * 32767).astype(np.int16))

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
           f"setpts={factor:.3f}*PTS,scale={VW}:{VH}:force_original_aspect_ratio=increase:flags=lanczos,"
           f"crop={VW}:{VH},eq=contrast=1.05:saturation=1.08,colorbalance=rs=0.04:gs=0.01:bs=-0.04,"
           f"gblur=sigma=0.5,noise=alls=7:allf=t,pad={W}:{H}:0:{VY}:black,"
           f"fps={FPS},tpad=stop_mode=clone:stop_duration=3",
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
            f"Style: S,DejaVu Sans,46,&H0033E6FF,&H000000FF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,3,1,2,60,60,{H - VY - VH + 22},1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    ev = [f"Dialogue: 0,{ass_time(a)},{ass_time(b)},S,,0,0,0,,{{\\fad(120,120)}}{x.replace('{', '(').replace('}', ')')}"
          for a, b, x in subs]
    ass.write_text(head + "\n".join(ev) + "\n", encoding="utf-8")

    vf = f"subtitles={ass.name}"
    headline = (sc.get("headline") or sc.get("title") or "").strip()
    if headline:
        import textwrap
        lines = textwrap.wrap(headline, 30)[:4]
        fs, lh = (66, 80) if HEAD_FONT != FONT else (58, 74)
        y0 = VY - 50 - lh * len(lines)
        for k, ln in enumerate(lines):
            (work / f"hl_{k}.txt").write_text(ln, encoding="utf-8")
            vf += (f",drawtext=fontfile={HEAD_FONT}:textfile=hl_{k}.txt:fontsize={fs}:fontcolor=white:"
                   f"x=(w-tw)/2:y={y0 + k * lh}:enable='lt(t,{total - end_len:.2f})'")
    final = work / f"{vid}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", joined.name, "-i", "mix.wav",
                    "-vf", vf, "-map", "0:v", "-map", "1:a",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-r", str(FPS),
                    "-af", "loudnorm=I=-14:TP=-1.5:LRA=9", "-c:a", "aac", "-b:a", "256k", "-ar", "48000",
                    "-shortest", "-movflags", "+faststart", final.name], cwd=work, check=True)
    poster = work / "poster.jpg"
    sh("ffmpeg", "-y", "-loglevel", "error", "-ss", "2.5", "-i", final, "-frames:v", "1", "-vf", "scale=540:-2", poster)

    # Ablage als GitHub-Release (öffentlicher Link fürs Dashboard und später für Instagram/TikTok)
    urls = upload_release(vid, sc.get("title") or vid, [final, poster])
    notes = gpu["notes"] + sorted(voice_notes) + [
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
