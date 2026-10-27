#!/usr/bin/env python3
"""
True-Crime-Dokus (deutsch) – auf der sicheren Seite:

  * nur gut dokumentierte, ABGESCHLOSSENE Fälle (Täter rechtskräftig verurteilt, mind. 25 Jahre her) oder berühmte
    ungelöste historische Fälle OHNE Verdächtige zu nennen
  * Opfer, Angehörige, Zeugen, Polizisten: keine Namen; Täter nur mit Namen, wenn verurteilt + historisch + bekannt
  * Grundlage ist der komplette Wikipedia-Artikel; ein zweiter Durchgang prüft jeden Satz gegen die Quelle,
    Unbelegtes fliegt raus und wird für die Freigabe gelistet
  * Bilder nur Atmosphäre (keine Gesichter echter Menschen), ruhiger Doku-Ton, Quellen in der Beschreibung
  * Upload als PRIVAT – öffentlich erst nach deiner Freigabe

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
UA = {"User-Agent": "youtube-automatik/1.0 (true crime research; contact via GitHub)"}
STYLE = ("cinematic documentary still, moody, muted desaturated colors, film grain, atmospheric, dusk or night, "
         "no people's faces, no text, no logos, no gore, no blood, no weapons, no dead bodies")

PICK_TASK = """Du planst eine seriöse deutschsprachige True-Crime-Doku (YouTube, ca. {minutes} Minuten).
Wähle EINEN Fall, der ALLE Bedingungen erfüllt:
- sehr gut dokumentiert, mit eigenem ausführlichem deutschen Wikipedia-Artikel
- entweder: Täter rechtskräftig verurteilt UND die Tat liegt mindestens 25 Jahre zurück
  oder: berühmter ungelöster historischer Fall (mind. 40 Jahre her), bei dem KEINE lebenden Verdächtigen benannt werden
- keine Taten an Kindern, keine Sexualverbrechen, keine Terroranschläge, keine Fälle mit noch laufenden Verfahren
- spannend erzählbar (Ermittlung, Wendepunkte, Auflösung), z. B. berühmte Kriminalfälle, Betrugs- und Raubfälle,
  historische Mordfälle, spektakuläre Ausbrüche, Kunstraub, Entführungen mit gutem Ausgang
Bevorzugt Fälle aus Deutschland, Österreich, Schweiz oder weltbekannte Fälle.
Diese Fälle hatten wir schon: {used}
Antworte NUR mit JSON: {{"case":"kurzer Name des Falls","wiki_title":"exakter Titel des deutschen Wikipedia-Artikels",
"why":"1 Satz, warum er die Bedingungen erfüllt","year":1970}}"""

SCRIPT_TASK = """Schreibe das Sprechskript einer ruhigen, seriösen deutschen True-Crime-Doku (Stil: Dokumentarfilm,
nicht reißerisch). Länge ca. {words} Wörter in {segs} Abschnitten (je 2–4 Sätze).
NUR Fakten aus der QUELLE unten verwenden – nichts erfinden, keine Zitate erfinden, keine Gedanken/Gefühle von
Beteiligten ausdenken, Unsicheres als unsicher kennzeichnen ("Laut Gericht…", "Bis heute ist unklar…").
Namen: Opfer, Angehörige, Zeugen, Ermittler NICHT namentlich nennen (z. B. "eine 34-jährige Frau", "der Ermittler").
Täter nur namentlich, wenn rechtskräftig verurteilt; sonst "der Täter"/"ein Verdächtiger" ohne Namen.
Keine grausamen Details, kein Blut, keine Beschreibung von Verletzungen. Respektvoll gegenüber Opfern.
Aufbau: ruhiger, packender Einstieg (Ort, Zeit, Atmosphäre) – Tat (ohne Grausamkeit) – Ermittlungen und Wendepunkte –
Auflösung/Urteil – Nachwirkung – nachdenklicher Schluss + Frage an die Zuschauer.
Für JEDEN Abschnitt eine Bildidee NUR mit Atmosphäre, ohne Menschen-Gesichter (z. B. "verregnete Kopfsteinpflaster-
straße in einer Kleinstadt bei Nacht, 1970er", "Stapel alter Akten auf einem Holztisch, Schreibtischlampe").
Außerdem: title (max 70 Zeichen, seriös neugierig machend, kein Clickbait-Lügen),
description (3 Sätze), short (ein eigenständiger 50–70-Wort-Teaser für einen YouTube-Short, endet mit
"Die ganze Geschichte auf dem Kanal.").
Antworte NUR mit JSON: {{"title":"...","description":"...","segments":[{{"text":"...","visual":"..."}}],"short":"..."}}

QUELLE ({source_name}):
{source}"""

CHECK_TASK = """Prüfe dieses Doku-Skript Satz für Satz gegen die QUELLE.
Entferne oder korrigiere jede Aussage, die nicht eindeutig durch die Quelle belegt ist (Daten, Zahlen, Orte, Abläufe,
Zitate, Motive). Entferne Namen von Opfern, Angehörigen, Zeugen, Ermittlern und nicht verurteilten Personen.
Entferne grausame Details. Stil und Länge möglichst erhalten.
Gib das korrigierte Skript im GLEICHEN JSON-Format zurück und zusätzlich "removed": Liste der entfernten/geänderten
Aussagen (jeweils kurz, mit Grund). Antworte NUR mit JSON.

QUELLE:
{source}

SKRIPT:
{script}"""


def used():
    try:
        return json.loads(USED.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def wiki_de(title):
    """Kompletter Artikeltext (de.wikipedia) + URL."""
    r = requests.get("https://de.wikipedia.org/w/api.php", headers=UA, timeout=40, params={
        "action": "query", "prop": "extracts|info", "explaintext": 1, "titles": title, "redirects": 1,
        "inprop": "url", "format": "json"}).json()
    page = next(iter(r.get("query", {}).get("pages", {}).values()), {})
    if not page or "missing" in page:
        s = requests.get("https://de.wikipedia.org/w/api.php", headers=UA, timeout=40, params={
            "action": "query", "list": "search", "srsearch": title, "srlimit": 1, "format": "json"}).json()
        hits = s.get("query", {}).get("search", [])
        if not hits:
            return "", "", ""
        return wiki_de(hits[0]["title"]) if hits[0]["title"] != title else ("", "", "")
    return page.get("title", title), page.get("extract", ""), page.get("fullurl", "")


def plan(minutes, log=print):
    for attempt in range(4):
        pick = gemini.ask_json(PICK_TASK.format(minutes=int(minutes), used="; ".join(used()[-80:]) or "keine"),
                               temperature=1.0)
        title, text, url = wiki_de(pick["wiki_title"])
        if len(text) >= 6000:                       # nur ausführlich dokumentierte Fälle
            break
        log(f"  ↻ Quelle zu dünn ({pick.get('case')}: {len(text)} Zeichen) – anderer Fall")
    else:
        raise SystemExit("Kein ausreichend dokumentierter Fall gefunden.")
    log(f"▶ Fall: {pick['case']} – {title} ({len(text)} Zeichen Quelle)")
    words = int(minutes * 135)
    src = text[:45000]
    sc = gemini.ask_json(SCRIPT_TASK.format(words=words, segs=max(12, words // 55), source=src,
                                            source_name=f"Wikipedia: {title}"), temperature=0.6)
    checked = gemini.ask_json(CHECK_TASK.format(source=src, script=json.dumps(sc, ensure_ascii=False)), temperature=0.1)
    removed = checked.pop("removed", [])
    if checked.get("segments"):
        sc = checked
    sc.update(case=pick["case"], why=pick.get("why", ""), source_title=title, source_url=url, removed=removed)
    return sc


# ----------------------------------------------------------------- Stimme (deutsch, mit Prüfung gegen Nachplappern)
def narrate_de(voice, ref, texts, work, tag):
    import tts
    parts, subs, t = [], [], 0.0
    for i, s in enumerate(texts):
        best = None
        for seed in (5, 17, 29):
            wav = voice.speak.remote(s, ref_wav=ref, exaggeration=0.45, cfg_weight=0.5, language="de", seed=seed + i)
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
    from modal_app import ImageFlux, VoiceDE, app, download_flux
    ref_p = ROOT / "data" / "voices" / os.environ.get("TC_VOICE", "ref_sulafat.wav")
    ref = ref_p.read_bytes() if ref_p.exists() else b""
    t0 = _t.time()
    with modal.enable_output(), app.run():
        download_flux.remote()
        voice, flux = VoiceDE(), ImageFlux()
        seg_audio, seg_subs = [], []
        for i, s in enumerate(segs):
            a, subs = narrate_de(voice, ref, wi.sentences(s["text"]), work, f"s{i}")
            seg_audio.append(a)
            seg_subs.append(subs)
            log(f"  Stimme {i + 1}/{len(segs)} ({_t.time() - t0:.0f} s)")
        imgs = []
        for i, s in enumerate(segs):
            png = flux.generate.remote(f"{s.get('visual', 'old case files on a wooden desk')}, {STYLE}", seed=300 + i)
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
    wi.karaoke_ass(wi.word_times(voice_all, all_subs, lang="de"), work / "subs.ass", 1920, 1080, 64, 80)
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
    wi.karaoke_ass(wi.word_times(sh_audio, sh_subs, lang="de"), work / "sh.ass", 1080, 1920, 84, 0, align=5, upper=True)
    wi.mix_and_render(work / "sh.mp4", sh_audio, out / "short.mp4", work, work / "sh.ass", music_db=-25)
    # Begleittext für die Freigabe
    total = len(voice_all) / SR
    review = [f"FALL: {sc['case']}  ({sc.get('why', '')})", f"Quelle: {sc['source_url']}",
              f"Titel: {sc['title']}", f"Länge: {total / 60:.1f} min", "",
              "VOM FAKTENCHECK ENTFERNT/GEÄNDERT:"] + [f"- {r}" for r in sc.get("removed", [])] + \
             ["", "SKRIPT:"] + [f"[{i + 1}] {s['text']}" for i, s in enumerate(segs)] + ["", "SHORT:", sc["short"]]
    (out / "skript_zur_freigabe.txt").write_text("\n".join(review), encoding="utf-8")
    meta = {"title": sc["title"][:100], "case": sc["case"], "source_url": sc["source_url"],
            "description": (f"{sc['description']}\n\nQuelle: Wikipedia – {sc['source_title']}: {sc['source_url']}\n"
                            "Alle Angaben beruhen auf öffentlich zugänglichen Quellen. Namen von Opfern und Angehörigen "
                            "werden aus Respekt nicht genannt. Bilder: KI-generierte Symbolbilder, keine echten Personen "
                            "oder Orte.\n\n#truecrime #kriminalfall #doku"),
            "short_title": f"{sc['case']} – wahre Geschichte #shorts"[:100], "short_text": sc["short"],
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
    d.rectangle([64, 52, 64 + 250, 104], fill=(178, 34, 34))
    d.text((80, 56), "WAHRER FALL", font=ImageFont.truetype(str(fp), 40) if fp.exists() else f, fill="white")
    im.save(out, quality=92)


def upload_private(out: Path, meta: dict):
    """Lädt Video + Short PRIVAT hoch – öffentlich erst nach Freigabe."""
    import upload
    tok = os.environ.get("YT_REFRESH_TOKEN_TRUECRIME")
    if not tok:
        print("  (kein YouTube-Zugang für True Crime – nur Vorschau)")
        return
    yt = upload.service(tok)
    ch = {"name": "truecrime", "category_id": "25", "made_for_kids": False, "privacy": "private", "synthetic": True}
    vid = upload.upload(yt, out / "video.mp4", {"title": meta["title"], "description": meta["description"],
                                                "tags": ["true crime", "kriminalfall", "doku", "wahre geschichte"]}, ch)
    try:
        upload.set_thumbnail(yt, vid, out / "thumbnail.jpg")
    except Exception:  # noqa: BLE001
        pass
    svid = upload.upload(yt, out / "short.mp4", {"title": meta["short_title"], "description":
                         f"{meta['short_text']}\n\nQuelle: {meta['source_url']}\n#shorts #truecrime"}, ch)
    print(f"::notice title=Zur Freigabe::Video https://youtu.be/{vid} und Short https://youtu.be/{svid} liegen PRIVAT "
          "bereit – bitte ansehen und in YouTube Studio auf Öffentlich stellen.")
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
