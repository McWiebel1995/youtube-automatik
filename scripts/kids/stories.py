"""Gute-Nacht-Geschichten: Text wählen (oder per KI schreiben), vorlesen, bebildern, untertiteln."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import yaml
from scipy.io import wavfile
from scipy.signal import resample_poly

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import ASSETS, ROOT  # noqa: E402

import music  # noqa: E402
import tts  # noqa: E402
import visuals  # noqa: E402
from schlaf import render_loop  # noqa: E402

SR = 44100
LIB = ROOT / "data" / "stories.yaml"
USED = ROOT / "data" / "stories_used.json"


# ----------------------------------------------------------------- Text
def _used():
    return json.loads(USED.read_text(encoding="utf-8")) if USED.exists() else []


def mark_used(title):
    used = _used()
    used.append(title)
    USED.write_text(json.dumps(used, ensure_ascii=False, indent=1), encoding="utf-8")


def from_library(rnd):
    stories = yaml.safe_load(LIB.read_text(encoding="utf-8"))
    used = _used()
    fresh = [s for s in stories if s["title"] not in used]
    if not fresh:  # alle verwendet -> von vorn, ältestes zuerst
        order = {t: i for i, t in enumerate(used)}
        fresh = sorted(stories, key=lambda s: order.get(s["title"], -1))[:3]
    return rnd.choice(fresh)


def from_claude(rnd):
    """Schreibt eine neue Geschichte mit Claude (Secret ANTHROPIC_API_KEY)."""
    import anthropic

    animals = ["Igel", "Eichhörnchen", "Häschen", "Entlein", "Bärchen", "Kätzchen", "Schaf", "Maus",
               "Rehkitz", "Pinguin", "Schildkröte", "Otter", "Eule", "Marienkäfer"]
    themes = ["Freundschaft", "Mut", "Teilen", "Geduld", "Neugier", "Helfen", "Dankbarkeit", "Ruhe finden"]
    places = ["im Wald", "am See", "auf dem Bauernhof", "am Meer", "auf einer Blumenwiese", "in den Bergen",
              "im Garten", "unter dem Sternenhimmel"]
    used = _used()[-30:]
    prompt = (
        "Schreibe eine neue, ruhige Gute-Nacht-Geschichte auf Deutsch für Kinder von 2 bis 6 Jahren.\n"
        f"Hauptfigur: ein {rnd.choice(animals)}. Ort: {rnd.choice(places)}. Thema: {rnd.choice(themes)}.\n"
        "Regeln: 300 bis 450 Wörter, 6 bis 8 Absätze, kurze einfache Sätze, keine Anführungszeichen "
        "(wörtliche Rede einfach mit 'sagte' einleiten), nichts Gruseliges, keine Gefahr, keine Markennamen "
        "oder bekannten Figuren. Die Geschichte wird zum Ende hin immer ruhiger und endet damit, dass die "
        "Figur einschläft, plus ein sanftes 'Gute Nacht'.\n"
        f"Diese Titel gab es schon, wähle etwas anderes: {', '.join(used) or '–'}\n"
        'Antworte NUR mit JSON: {"title": "...", "paragraphs": ["...", "..."]}'
    )
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5"),
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    data = json.loads(text[text.index("{"): text.rindex("}") + 1])
    assert data["title"] and len(data["paragraphs"]) >= 4
    return data


ANIMALS = ["Igel", "Eichhörnchen", "Häschen", "Entlein", "Bärchen", "Kätzchen", "Schaf", "Maus", "Rehkitz",
           "Pinguin", "Schildkröte", "Otter", "Eule", "Marienkäfer", "Fuchs", "Dachs", "Glühwürmchen", "Frosch",
           "Elefantenkind", "Seehund", "Küken", "Waschbär", "Koala", "Faultier"]
THEMES = ["Freundschaft", "Mut", "Teilen", "Geduld", "Neugier", "Helfen", "Dankbarkeit", "Ruhe finden",
          "Anderssein", "Verzeihen", "Heimweh", "etwas Neues lernen", "Zuhören"]
PLACES = ["im Wald", "am See", "auf dem Bauernhof", "am Meer", "auf einer Blumenwiese", "in den Bergen",
          "im Garten", "unter dem Sternenhimmel", "in einem verschneiten Dorf", "auf einer kleinen Insel",
          "in einem alten Leuchtturm", "auf einer Wolke"]


def from_gemini(rnd):
    """Schreibt eine neue lange Geschichte (~12 Min.) + Mini-Version für den Short (Gemini, Gratis-Kontingent)."""
    sys.path.insert(0, str(ROOT / "anime"))
    import gemini

    used = _used()[-40:]
    prompt = (
        "Schreibe eine neue, ruhige Gute-Nacht-Geschichte auf Deutsch für Kinder von 2 bis 6 Jahren.\n"
        f"Hauptfigur: ein {rnd.choice(ANIMALS)}. Ort: {rnd.choice(PLACES)}. Thema: {rnd.choice(THEMES)}.\n"
        "Regeln: 1100 bis 1400 Wörter, 12 bis 16 Absätze, kurze einfache Sätze, keine Anführungszeichen "
        "(wörtliche Rede einfach mit 'sagte' einleiten), nichts Gruseliges, keine Gefahr, keine Markennamen "
        "oder bekannten Figuren. Liebevolle Details (Geräusche, Farben, Gerüche), ein, zwei Nebenfiguren. "
        "Die Geschichte wird zum Ende hin immer ruhiger und endet damit, dass die Figur einschläft, "
        "plus ein sanftes 'Gute Nacht'.\n"
        "Zusätzlich eine MINI-Version für einen 45-Sekunden-Clip: 55 bis 75 Wörter, beginnt neugierig machend, "
        "endet mit dem Satz: Die ganze Geschichte hörst du auf unserem Kanal. Gute Nacht!\n"
        f"Diese Titel gab es schon, wähle etwas anderes: {', '.join(used) or '–'}\n"
        'Antworte NUR mit JSON: {"title": "...", "paragraphs": ["...", "..."], "mini": "..."}'
    )
    data = gemini.ask_json(prompt, temperature=0.95)
    assert data["title"] and len(data["paragraphs"]) >= 6 and data.get("mini")
    words = sum(len(p.split()) for p in data["paragraphs"])
    while words > 1600 and len(data["paragraphs"]) > 8:     # max. ~14 Minuten
        words -= len(data["paragraphs"].pop(len(data["paragraphs"]) // 2).split())
    return data


def mini_of(story):
    """Mini-Text für den Short (falls die KI keinen geliefert hat)."""
    if story.get("mini"):
        return story["mini"]
    text, out = " ".join(story["paragraphs"][:2]), []
    for s_ in sentences(text):
        if len(" ".join(out + [s_]).split()) > 55:
            break
        out.append(s_)
    return " ".join(out) + " Wie es weitergeht, hörst du in der ganzen Geschichte auf unserem Kanal. Gute Nacht!"


def pick_story(ch, rnd):
    if ch.get("ai_stories") and os.environ.get("GEMINI_API_KEY"):
        try:
            return from_gemini(rnd), "ki"
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ Gemini-Geschichte fehlgeschlagen ({str(e)[:200]})")
    if ch.get("ai_stories") and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return from_claude(rnd), "ki"
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ KI-Geschichte fehlgeschlagen ({e}) – nehme eine aus der Sammlung.")
    return from_library(rnd), "sammlung"


def sentences(paragraph):
    parts = re.split(r"(?<=[.!?])\s+", paragraph.strip())
    return [p for p in parts if p]


# ----------------------------------------------------------------- Ton + Untertitel
def ass_time(t):
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def build(story, work, voice, rate, rnd):
    lines = [(f"Heute erzähle ich dir eine Geschichte. Sie heißt: {story['title']}.", 1.4)]
    for para in story["paragraphs"]:
        ss = sentences(para)
        for i, s in enumerate(ss):
            lines.append((s, 1.1 if i == len(ss) - 1 else 0.45))
    pieces, subs, t = [np.zeros(int(2.0 * SR))], [], 2.0
    for i, (text, pause) in enumerate(lines):
        wav = work / f"l_{i:03d}.wav"
        tts.speak(text, wav, voice, rate)
        sr, data = wavfile.read(wav)
        data = data.astype(np.float32) / 32768
        if data.ndim > 1:
            data = data.mean(axis=1)
        if sr != SR:
            data = resample_poly(data, SR, sr).astype(np.float32)
        dur = len(data) / SR
        subs.append((t, t + dur + min(pause, 0.6), text))
        pieces += [data, np.zeros(int(pause * SR))]
        t += dur + pause
        wav.unlink(missing_ok=True)
    pieces.append(np.zeros(int(6 * SR)))  # Musik klingt aus
    voice_track = np.concatenate(pieces)
    vpath = work / "voice.wav"
    wavfile.write(vpath, SR, (np.clip(voice_track, -1, 1) * 32767).astype(np.int16))
    return vpath, subs, len(voice_track) / SR


def write_ass(path, title, subs, font_name, title_font=None):
    def esc(s):
        return s.replace("{", "(").replace("}", ")")

    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{font_name},54,&H00F5F5FF,&H000000FF,&H00301818,&H64000000,0,0,0,0,100,100,0,0,1,3,1,2,160,160,70,1
Style: Title,{title_font or font_name},140,&H00C8F0FF,&H000000FF,&H00301818,&H64000000,1,0,0,0,100,100,0,0,1,5,2,8,100,100,150,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = [f"Dialogue: 0,{ass_time(0.3)},{ass_time(6.5)},Title,,0,0,0,,{{\\fad(800,800)}}{esc(title)}"]
    for a, b, text in subs:
        ev.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Sub,,0,0,0,,{{\\fad(250,250)}}{esc(text)}")
    path.write_text(head + "\n".join(ev) + "\n", encoding="utf-8")


def ensure_loops(variants=4, seconds=20):
    out_dir = ASSETS / "geschichten" / "video"
    out_dir.mkdir(parents=True, exist_ok=True)
    for v in range(1, variants + 1):
        out = out_dir / f"book_{v:02d}.mp4"
        if not out.exists():
            render_loop(visuals.bilderbuch, 900 + v, seconds, out)
            print(f"  ✓ {out.relative_to(ROOT)}")
    return sorted(out_dir.glob("*.mp4"))


# ----------------------------------------------------------------- Hauptfunktion
def produce(ch, work: Path, rnd, voice, rate):
    work.mkdir(parents=True, exist_ok=True)
    story, source = pick_story(ch, rnd)
    print(f"  Geschichte: {story['title']} ({source})")
    loop = rnd.choice(ensure_loops())
    vpath, subs, total = build(story, work, voice, rate, rnd)
    m = music.lullaby(rnd.randrange(2**31), repeats=2, bpm=(48, 58))
    mpath = work / "music.wav"
    wavfile.write(mpath, SR, (np.clip(m, -1, 1) * 32767).astype(np.int16))

    fdir = ROOT / "assets" / "fonts"
    font_name = "Nunito" if (fdir / "Nunito.ttf").exists() else "Fredoka" if (fdir / "Kids.ttf").exists() else "DejaVu Sans"
    title_font = "Baloo 2" if (fdir / "Baloo2.ttf").exists() else font_name
    write_ass(work / "story.ass", story["title"], subs, font_name, title_font)
    fonts_dir = (ROOT / "assets" / "fonts").as_posix()

    out = work / "video.mp4"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-stream_loop", "-1", "-i", str(loop), "-i", vpath.name, "-stream_loop", "-1", "-i", mpath.name,
           "-filter_complex",
           f"[0:v]subtitles=story.ass:fontsdir='{fonts_dir}',fade=t=out:st={total - 4}:d=4[v];"
           f"[2:a]volume=-24dB,afade=t=out:st={total - 8}:d=8[m];[1:a][m]amix=inputs=2:normalize=0:duration=first,"
           "loudnorm=I=-18:TP=-1.5:LRA=11,aresample=44100[a]",
           "-map", "[v]", "-map", "[a]", "-t", f"{total:.2f}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out.name]
    res = subprocess.run(cmd, cwd=work, capture_output=True, text=True)
    if res.returncode:
        raise RuntimeError(res.stderr)
    for f in (vpath, mpath):
        f.unlink(missing_ok=True)
    return {"video_file": str(out), "loop": str(loop), "story": story, "source": source,
            "seconds": round(total, 1)}


def metadata(ch, info, rnd):
    st = info["story"]
    title = rnd.choice(ch["title_templates"]).format(title=st["title"])[:100]
    mins = max(1, round(info["seconds"] / 60))
    teaser = sentences(st["paragraphs"][0])[:2]
    desc = "\n".join([
        f"🌙 {st['title']} – eine ruhige Gute-Nacht-Geschichte zum Zuhören (ca. {mins} Minuten).",
        "",
        " ".join(teaser),
        "",
        "Perfekt zum Einschlafen: sanfte Stimme, leise Spieluhr-Musik und ein ruhiges Bild.",
        "Für Kinder von ca. 2 bis 6 Jahren.",
        "",
        "Alle Geschichten, Bilder und Melodien wurden für diesen Kanal erstellt."
        + (" Die Geschichte wurde mit KI-Unterstützung geschrieben und von uns geprüft." if info["source"] == "ki" else ""),
        "",
        "#GuteNachtGeschichte #Einschlafgeschichte #Kindergeschichten",
    ])
    return {"title": title, "description": desc, "tags": ch["tags"], "scene": st["title"]}
