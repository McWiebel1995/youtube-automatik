#!/usr/bin/env python3
"""
Krimi-Geschichten im True-Crime-Stil (englisch) – FIKTIV und klar gekennzeichnet:

  * erfundene Fälle, angelehnt an typische echte Fallmuster; alle Namen, Orte, Details erfunden (fiktive Kleinstädte)
  * kein Bezug zu echten Personen/Fällen; keine Taten an Kindern, keine Sexualverbrechen, keine Grausamkeiten
  * Hinweis „This story is fictional …“ im ersten Satz, in der Beschreibung und als YouTube-KI-Kennzeichnung
  * Bilder nur Atmosphäre (keine Gesichter), ruhiger Doku-Erzähler, Karaoke-Untertitel; dazu ein Teaser-Short

    python scripts/truecrime.py --out output/truecrime [--dry-run] [--minutes 10]
"""
import argparse
import datetime as dt
import json
import os
import random
import re
import sys
import tempfile
from pathlib import Path

import numpy as np
import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(HERE / "kids"), str(ROOT / "anime")]
import gemini  # noqa: E402
import whatif as wi  # noqa: E402

SR = wi.SR
USED = ROOT / "data" / "truecrime_used.json"
STYLE = ("cinematic documentary still, moody, muted desaturated colors, film grain, atmospheric, dusk or night, "
         "quiet and empty scene, calm still life, tidy and clean")
NEGATIVE = ("blood, gore, weapon, gun, rifle, pistol, knife, corpse, dead body, injury, violence, crime scene tape, "
            "skull, face, portrait, person in focus, red stains")
BAD_WORDS = r"\b(blood\w*|bloody|gun\w*|rifle\w*|pistol\w*|knife|knives|weapon\w*|corpse\w*|body|bodies|dead|murder\w*|" \
            r"kill\w*|victim\w*|injur\w*|wound\w*|gore|crime scene|stab\w*|shot|shoot\w*)\b"


def safe_visual(v):
    """Bildidee entschärfen: heikle Wörter raus (der Bildgenerator malt sonst genau das)."""
    v = re.sub(BAD_WORDS, "", v or "", flags=re.I)
    return re.sub(r"\s{2,}", " ", v).strip(" ,.") or "old case files on a wooden desk under a desk lamp"

def used():
    try:
        return json.loads(USED.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


STORY_TASK = """Write an ORIGINAL, entirely FICTIONAL crime story told like a calm, serious true crime documentary
(narrator voice, investigation, twists, resolution). It is inspired by the kinds of cases that really happen
(theme for this episode: {theme}), but every person, place, date and detail is invented.
Hard rules:
- Invent all names (ordinary, believable names) and set it in a FICTIONAL small town or neighbourhood (invent the name;
  country/region may be generic, e.g. "a small town in the American Midwest"). Never use real people, real crimes,
  real victims, real companies, real police departments or real towns as the setting.
- Do not make it resemble a specific famous real case.
- No crimes against children, no sexual crimes, no terrorism; no gore, no blood, no description of injuries.
- The FIRST sentence of the first segment is exactly: "This story is fictional, inspired by the kinds of cases
  investigators face every day."
- Never call it a true story. Clever, fair twist; clues planted earlier; satisfying, plausible resolution.
Length about {words} words in {segs} segments (2–4 sentences each). Calm, atmospheric, gripping.
For EVERY segment a visual idea: a calm, EMPTY place or harmless object only (e.g. "rain-soaked main street of a quiet
town at night, 1990s", "old case files under a desk lamp", "an old fountain pen on a document"). Never mention weapons,
blood, bodies, victims or violence in the visual idea.
Also: title (max 70 chars, intriguing, must NOT claim it is true; e.g. "The Last Guest at Harrow Inn"),
description (2–3 sentences), short (a standalone 50–70-word teaser for a Short, first words "A fictional case:",
ending with "Full story on the channel."), case (short name of the story).
Avoid these previous stories/themes: {used}
Answer ONLY JSON: {{"case":"...","title":"...","description":"...","segments":[{{"text":"...","visual":"..."}}],
"short":"..."}}"""
THEMES = ["a disappearance in a small town", "a perfect-looking alibi", "an inheritance dispute", "a con artist",
          "a cold case reopened decades later", "a robbery that went wrong", "a lighthouse keeper's secret",
          "a missing hiker", "a family business with a dark secret", "an anonymous letter", "a fire at an old mill",
          "a stolen painting", "a forged will", "a snowed-in mountain lodge", "a vanished fortune",
          "a witness who saw too much", "a small-town radio host", "a wrong man convicted"]


def plan(minutes, log=print):
    words = int(minutes * 135)
    theme = random.choice(THEMES)
    sc = gemini.ask_json(STORY_TASK.format(theme=theme, words=words, segs=max(12, words // 55),
                                           used="; ".join(used()[-80:]) or "none"), temperature=0.95)
    first = sc["segments"][0]["text"]
    if "fictional" not in first.lower():           # Hinweis am Anfang erzwingen
        sc["segments"][0]["text"] = ("This story is fictional, inspired by the kinds of cases investigators face every "
                                     "day. " + first)
    if re.search(r"\btrue (story|case|crime)\b", sc["title"], re.I):
        sc["title"] = re.sub(r"\btrue (story|case|crime)\b", "", sc["title"], flags=re.I).strip(" -–:")
    sc.update(theme=theme, source_title="", source_url="", removed=[], why=f"fiktiv, Thema: {theme}")
    log(f"▶ Fiktiver Fall: {sc['case']} ({theme}) – {sc['title']}")
    return sc


# ----------------------------------------------------------------- Stimme (deutsch, mit Prüfung gegen Nachplappern)
def narrate_de(voice, ref, texts, work, tag):
    import tts
    parts, subs, t = [], [], 0.0
    for i, s in enumerate(texts):
        best = None
        for seed in (5, 17, 29):
            wav = voice.speak.remote(s, ref, exaggeration=0.45, cfg_weight=0.5, seed=seed + i)
            a, sr, too_long = tts._clean(wav, s)
            if best is None or not too_long:
                best = (a, sr)
            if not too_long:
                break
        a, sr = best
        p = work / f"{tag}_{i}.wav"
        from scipy.io import wavfile
        wavfile.write(p, sr, (np.clip(a, -1, 1) * 32767).astype(np.int16))
        a = wi.to_sr(p.read_bytes(), work, f"{tag}_{i}_r.wav")
        subs.append((t, t + len(a) / SR, s))
        parts += [a, np.zeros(int(0.42 * SR), np.float32)]
        t += len(a) / SR + 0.42
    return (np.concatenate(parts) if parts else np.zeros(SR, np.float32)), subs


# ----------------------------------------------------------------- Ablauf
def build(out: Path, minutes=10.0, seed=None, log=print):
    import time as _t
    rnd = random.Random(seed)
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=out))
    sc = plan(minutes, log)
    segs = sc["segments"]
    import modal
    from modal_app import ImageFlux, Voice, app, download_flux
    ref_p = ROOT / "data" / "voices" / os.environ.get("TC_VOICE", "anime/narrator.wav")
    ref = ref_p.read_bytes() if ref_p.exists() else b""
    t0 = _t.time()
    with modal.enable_output(), app.run():
        download_flux.remote()
        voice, flux = Voice(), ImageFlux()
        seg_audio, seg_subs = [], []
        for i, s in enumerate(segs):
            a, subs = narrate_de(voice, ref, wi.sentences(s["text"]), work, f"s{i}")
            seg_audio.append(a)
            seg_subs.append(subs)
            log(f"  Stimme {i + 1}/{len(segs)} ({_t.time() - t0:.0f} s)")
        imgs = []
        for i, s in enumerate(segs):
            png = flux.generate.remote(f"{safe_visual(s.get('visual'))}, {STYLE}", seed=300 + i, negative=NEGATIVE)
            p = work / f"img_{i}.png"
            p.write_bytes(png)
            imgs.append(p)
            log(f"  Bild {i + 1}/{len(segs)} ({_t.time() - t0:.0f} s)")
        sh_audio, sh_subs = narrate_de(voice, ref, wi.sentences(sc["short"]), work, "short")
    # langes Video
    fade = 0.6
    clips, durs, all_subs, t = [], [], [], 0.0
    for i, (img, a, subs) in enumerate(zip(imgs, seg_audio, seg_subs)):
        d = len(a) / SR + (fade if i < len(segs) - 1 else 0)
        dst = work / f"seg_{i:02d}.mp4"
        wi.segment_video(img, dst, d, True, seed=i)
        clips.append(dst)
        durs.append(d)
        all_subs += [(t + x, t + y, txt) for x, y, txt in subs]
        t += len(a) / SR
    wi.xfade_concat(clips, durs, work / "joined.mp4", fade)
    voice_all = np.concatenate(seg_audio)
    wi.karaoke_ass(wi.word_times(voice_all, all_subs, lang="en"), work / "subs.ass", 1920, 1080, 64, 80)
    wi.mix_and_render(work / "joined.mp4", voice_all, out / "video.mp4", work, work / "subs.ass", music_db=-27)
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(imgs[0]), "-vf", "scale=1280:720", str(work / "th.png")],
                   check=True)
    thumbnail(work / "th.png", sc["title"], out / "thumbnail.jpg")
    # Short (9:16)
    per = len(sh_audio) / SR / 3 + fade
    sclips = []
    for j, img in enumerate(rnd.sample(imgs, min(3, len(imgs)))):
        dst = work / f"sh_{j}.mp4"
        wi.segment_video(img, dst, per, True, w=1080, h=1920, seed=50 + j)
        sclips.append(dst)
    wi.xfade_concat(sclips, [per] * len(sclips), work / "sh.mp4", fade)
    wi.karaoke_ass(wi.word_times(sh_audio, sh_subs, lang="en"), work / "sh.ass", 1080, 1920, 84, 0, align=5, upper=True)
    wi.mix_and_render(work / "sh.mp4", sh_audio, out / "short.mp4", work, work / "sh.ass", music_db=-25)
    # Begleittext für die Freigabe
    total = len(voice_all) / SR
    review = [f"FALL (fiktiv): {sc['case']}  ({sc.get('why', '')})",
              f"Titel: {sc['title']}", f"Länge: {total / 60:.1f} min", "",
              "VOM FAKTENCHECK ENTFERNT/GEÄNDERT:"] + [f"- {r}" for r in sc.get("removed", [])] + \
             ["", "SKRIPT:"] + [f"[{i + 1}] {s['text']}" for i, s in enumerate(segs)] + ["", "SHORT:", sc["short"]]
    (out / "skript_zur_freigabe.txt").write_text("\n".join(review), encoding="utf-8")
    meta = {"title": sc["title"][:100], "case": sc["case"], "source_url": sc["source_url"],
            "description": (f"{sc['description']}\n\n⚠️ This is a work of fiction, told in the style of a true crime "
                            "documentary and inspired by the kinds of cases that really happen. All names, places and "
                            "events are invented; any resemblance to real persons or cases is coincidental. "
                            "Images are AI-generated.\n\n#truecrimestories #crimestory #mystery"),
            "short_title": f"{sc['case']} 🔎 #shorts #mystery"[:100], "short_text": sc["short"],
            "minutes": round(total / 60, 1)}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    subprocess.run(["rm", "-rf", str(work)])
    return meta


def thumbnail(src, title, out):
    from PIL import Image, ImageDraw, ImageEnhance, ImageFont
    im = ImageEnhance.Brightness(Image.open(src).convert("RGB").resize((1280, 720))).enhance(0.55)
    d = ImageDraw.Draw(im)
    fp = ROOT / "assets" / "fonts" / "Anton.ttf"
    f = ImageFont.truetype(str(fp), 92) if fp.exists() else ImageFont.load_default()
    words, lines, cur = title.upper().split(), [], ""
    for w_ in words:
        tt = (cur + " " + w_).strip()
        if d.textlength(tt, font=f) > 1150 and cur:
            lines.append(cur)
            cur = w_
        else:
            cur = tt
    lines.append(cur)
    y = 720 - 70 - len(lines[:3]) * 100
    for ln in lines[:3]:
        d.text((64, y), ln, font=f, fill=(245, 240, 230), stroke_width=4, stroke_fill=(0, 0, 0))
        y += 100
    d.rectangle([64, 52, 64 + 236, 104], fill=(178, 34, 34))
    d.text((80, 56), "CASE FILE", font=ImageFont.truetype(str(fp), 40) if fp.exists() else f, fill="white")
    im.save(out, quality=92)


def upload_private(out: Path, meta: dict):
    """Lädt Video + Short PRIVAT hoch – öffentlich erst nach Freigabe."""
    import upload
    tok = os.environ.get("YT_REFRESH_TOKEN_TRUECRIME")
    if not tok:
        print("  (kein YouTube-Zugang für True Crime – nur Vorschau)")
        return
    yt = upload.service(tok)
    ch = {"name": "truecrime", "category_id": "24", "made_for_kids": False,
          "privacy": os.environ.get("TC_PRIVACY", "public"), "synthetic": True}
    vid = upload.upload(yt, out / "video.mp4", {"title": meta["title"], "description": meta["description"],
                                                "tags": ["crime story", "mystery", "true crime style", "fictional crime", "detective story"]}, ch)
    try:
        upload.set_thumbnail(yt, vid, out / "thumbnail.jpg")
    except Exception:  # noqa: BLE001
        pass
    svid = upload.upload(yt, out / "short.mp4", {"title": meta["short_title"], "description":
                         f"{meta['short_text']}\n\nA fictional story. #shorts #crimestory"}, ch)
    print(f"::notice title=Hochgeladen::Video https://youtu.be/{vid} · Short https://youtu.be/{svid}")
    u = used()
    USED.write_text(json.dumps((u + [meta["case"]])[-300:], ensure_ascii=False, indent=1), encoding="utf-8")
    upload.mark_uploaded("truecrime")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output/truecrime")
    ap.add_argument("--minutes", type=float, default=10)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    m = build(Path(a.out), a.minutes)
    if not a.dry_run:
        upload_private(Path(a.out), m)
    _ = dt
