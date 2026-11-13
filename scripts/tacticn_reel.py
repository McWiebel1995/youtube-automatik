#!/usr/bin/env python3
"""
Tacticn – Reihe „Zeichen erklärt“: echtes Bildschirmvideo vom Tacticn-Baukasten (tacticn.de) + Erklärtexte + Musik.

  python scripts/tacticn_reel.py --episode infanteriezug --out out/

Ablauf: Playwright filmt den Baukasten im Handyformat und stellt die Auswahl Schritt für Schritt um (Zugehörigkeit,
Einheitsebene). Danach legt ffmpeg Aufhänger, Erklärungen und Abschlusskarte darüber. Keine Stimme (Text + Musik).
"""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path

import requests

W, H = 1080, 1920
# Jede Folge: Seite + Schritte (Auswahlfeld per aria-label, Wert, Text dazu). Fakten nach APP-6(D).
EPISODES = {
    "infanteriezug": {
        "url": "https://tacticn.de/baukasten/10-1211",
        "title": "Infanteriezug",
        "hook": "Weißt du, was dieses\nZeichen bedeutet?",
        "steps": [
            (None, None, "Blaues Rechteck\n= eigene Truppe"),
            (None, None, "Das Kreuz\n= Infanterie"),
            ("Einheitsebene", "14", "Drei Punkte oben\n= Zug"),
            ("Zugehörigkeit", "6", "Rote Raute\n= feindliche Truppe"),
            ("Zugehörigkeit", "3", "Infanteriezug –\nin Sekunden gebaut"),
        ],
        "end": "Jedes Zeichen nach APP-6(D)\nals STL mit Magnet-Aussparung\n\nLink in Bio · tacticn.de",
        "caption": ("Weißt du, was dieses Zeichen bedeutet? 🎯\n\n"
                    "🟦 Blaues Rechteck = eigene Truppe\n✖️ Kreuz = Infanterie\n⚫⚫⚫ Drei Punkte = Zug\n"
                    "🟥 Rote Raute = feindliche Truppe\n\n"
                    "Folge 1 unserer Reihe „Zeichen erklärt“. Welches Zeichen sollen wir als Nächstes erklären? 👇\n\n"
                    "Alle Zeichen nach NATO APP-6(D) im Baukasten – als STL mit Magnet-Aussparung: Link in Bio.\n\n"
                    "#taktischezeichen #lagekarte #bundeswehr #reservisten #app6 #3ddruck #militär #tacticn"),
    },
}
STEP_S = 3.6          # Sekunden pro Erklärschritt
HOOK_S = 2.8
END_S = 3.4


def record(ep, work: Path):
    from playwright.sync_api import sync_playwright
    vid_dir = work / "rec"
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 432, "height": 768}, device_scale_factor=2.5, locale="de-DE",
                            record_video_dir=str(vid_dir), record_video_size={"width": W, "height": H},
                            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
                                       "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
        page = ctx.new_page()
        t0 = time.time()
        page.goto(ep["url"], wait_until="networkidle", timeout=60000)
        for txt in ("Nur notwendige", "Ablehnen", "Alle ablehnen", "Nur erforderliche"):   # Cookie-Hinweis: sparsam
            try:
                page.get_by_role("button", name=txt).first.click(timeout=1500)
                break
            except Exception:  # noqa: BLE001
                pass
        page.wait_for_timeout(1500)
        # Bildbereich mit dem Zeichen (2D-Referenz) in die obere Bildhälfte holen
        try:
            ref = page.get_by_text("2D-REFERENZ").first
            ref.scroll_into_view_if_needed(timeout=4000)
            page.evaluate("window.scrollBy(0, -20)")
        except Exception:  # noqa: BLE001
            pass
        page.screenshot(path=str(work / "debug_start.png"))
        marks = {"start": time.time() - t0}
        page.wait_for_timeout(int(HOOK_S * 1000))
        for i, (label, value, _txt) in enumerate(ep["steps"]):
            marks[f"s{i}"] = time.time() - t0
            if label:
                sel = page.locator(f'select[aria-label="{label}"]').first
                try:
                    sel.scroll_into_view_if_needed(timeout=3000)
                    page.wait_for_timeout(500)
                    sel.select_option(value)
                    page.wait_for_timeout(500)
                    ref = page.get_by_text("2D-REFERENZ").first
                    ref.scroll_into_view_if_needed(timeout=3000)
                    page.evaluate("window.scrollBy(0, -20)")
                except Exception as e:  # noqa: BLE001
                    print("Schritt", i, label, "fehlgeschlagen:", e)
            page.wait_for_timeout(int(STEP_S * 1000) - (1000 if label else 0))
        page.screenshot(path=str(work / "debug_end.png"))
        marks["end"] = time.time() - t0
        vpath = page.video.path()
        ctx.close()
        b.close()
    return Path(vpath), marks


def music(work: Path):
    """CC0-Musik von Freesound (keine Namensnennung nötig); ohne Schlüssel: Stille."""
    key = os.environ.get("FREESOUND_API_KEY")
    if not key:
        return None
    r = requests.get("https://freesound.org/apiv2/search/text/", timeout=30, params={
        "query": "cinematic tension drums", "filter": 'license:"Creative Commons 0" duration:[25 TO 120]',
        "fields": "id,name,previews,license,duration", "sort": "rating_desc", "page_size": 8, "token": key})
    for s in r.json().get("results", []):
        if s.get("previews"):
            p = work / "music.mp3"
            p.write_bytes(requests.get(s["previews"]["preview-hq-mp3"], timeout=60).content)
            print("Musik:", s["name"], s["license"])
            return p
    return None


def ass_time(t):
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def compose(ep, rec: Path, marks, work: Path, out: Path, font_dir: Path):
    start = marks["start"]
    total = marks["end"] - start + END_S
    ev = [f"Dialogue: 2,{ass_time(0)},{ass_time(HOOK_S)},Hook,,0,0,0,,{{\\fad(150,200)}}" + ep["hook"].replace("\n", "\\N")]
    for i, (_l, _v, txt) in enumerate(ep["steps"]):
        a = marks[f"s{i}"] - start
        b = (marks[f"s{i + 1}"] - start) if f"s{i + 1}" in marks else marks["end"] - start
        ev.append(f"Dialogue: 1,{ass_time(a + 0.2)},{ass_time(b)},Step,,0,0,0,,{{\\fad(150,150)}}" + txt.replace("\n", "\\N"))
    e0 = marks["end"] - start
    ev.append(f"Dialogue: 3,{ass_time(e0)},{ass_time(total)},End,,0,0,0,,{{\\fad(200,0)}}" + ep["end"].replace("\n", "\\N"))
    ev.append(f"Dialogue: 0,{ass_time(HOOK_S)},{ass_time(e0)},Tag,,0,0,0,,ZEICHEN ERKLÄRT · FOLGE 1 · {ep['title'].upper()}")
    ass = work / "t.ass"
    ass.write_text(f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,Oswald,104,&H00FFFFFF,&H000000FF,&H00203020,&H00203020,1,0,0,0,100,100,0,0,1,7,0,5,60,60,0,1
Style: Step,Oswald,86,&H00FFFFFF,&H000000FF,&H00203D2D,&HB0203D2D,1,0,0,0,100,100,0,0,3,26,0,2,70,70,170,1
Style: Tag,Oswald,38,&H0082BECB,&H000000FF,&H00000000,&HA0000000,1,0,0,0,100,100,1,0,3,12,0,8,40,40,60,1
Style: End,Oswald,72,&H0082BECB,&H000000FF,&H00203020,&H00203020,1,0,0,0,100,100,0,0,1,4,0,5,70,70,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(ev) + "\n", encoding="utf-8")
    mus = music(work)
    # Video ab Start, letzte Szene als Standbild für die Abschlusskarte verlängern, Hook-Phase und Abschluss abdunkeln
    flt = (f"[0:v]trim=start={start:.2f},setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={END_S},"
           f"scale={W}:{H},fps=30,"
           f"drawbox=t=fill:c=0x1a2416@0.62:enable='lt(t,{HOOK_S})',"
           f"drawbox=t=fill:c=0x1a2416@0.88:enable='gte(t,{e0:.2f})',"
           f"subtitles={ass.name}:fontsdir={font_dir}[v]")
    args = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(rec)]
    if mus:
        args += ["-stream_loop", "-1", "-i", str(mus)]
        flt += f";[1:a]atrim=0:{total:.2f},volume=0.55,afade=t=in:d=0.6,afade=t=out:st={total - 1.2:.2f}:d=1.2[a]"
    else:
        args += ["-f", "lavfi", "-t", f"{total:.2f}", "-i", "anullsrc=r=48000:cl=stereo"]
        flt += ";[1:a]anull[a]"
    args += ["-filter_complex", flt, "-map", "[v]", "-map", "[a]", "-t", f"{total:.2f}", "-c:v", "libx264",
             "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
             "-movflags", "+faststart", str(out)]
    subprocess.run(args, check=True, cwd=work)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", default="infanteriezug")
    ap.add_argument("--out", default="out")
    ap.add_argument("--fonts", default="fonts")
    a = ap.parse_args()
    ep = EPISODES[a.episode]
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    work = out / "work"
    work.mkdir(exist_ok=True)
    rec, marks = record(ep, work)
    print("Zeitmarken:", json.dumps({k: round(v, 2) for k, v in marks.items()}))
    mp4 = out / f"tacticn_{a.episode}.mp4"
    compose(ep, rec, marks, work, mp4, Path(a.fonts).resolve())
    (out / f"tacticn_{a.episode}.txt").write_text(ep["caption"], encoding="utf-8")
    print("::notice title=Tacticn-Reel::", mp4.name, round(marks["end"] - marks["start"] + END_S, 1), "s")


if __name__ == "__main__":
    main()
