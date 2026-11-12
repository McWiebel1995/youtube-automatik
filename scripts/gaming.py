#!/usr/bin/env python3
"""
Gaming-Kanal (Arbeitstitel): tägliche Gaming-News-Shorts, komplett generiert – ohne fremde Clips.

  python scripts/gaming.py --out output/gaming            # Short bauen (Test, kein Upload)
  python scripts/gaming.py --out output/gaming --publish  # bauen + hochladen (sobald Kanal & Token da sind)

Rechtlich sicher bleiben: keine Trailer-/Gameplay-Ausschnitte, keine echten Spielfiguren, keine Logos. Bilder sind
KI-Illustrationen im Stil ("neon city, sports car, palm trees"), Spielnamen nur im Text (beschreibend erlaubt).
Nutzt die Bausteine von Beyond the If (Nachrichten, Stimme, Untertitel, Schnitt).
"""
import argparse
import json
import os
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT / "anime")]
import gemini  # noqa: E402
import whatif as wi  # noqa: E402

SR = wi.SR
USED = ROOT / "data" / "gaming_used.json"
CFG = {"name": os.environ.get("GAMING_CHANNEL_NAME", "Gaming"), "token_secret": "YT_REFRESH_TOKEN_GAMING", "category_id": "20"}
NEGATIVE = ("logo, brand name, text, watermark, letters, real person, celebrity, famous character, game character, "
            "Rockstar, GTA logo, trademark, gore, blood, weapon pointed at viewer")
TASK = """You run a faceless daily gaming news channel for YouTube Shorts / Instagram Reels (audience: gamers 16–35, US).
Today's gaming headlines:
{news}
Already covered recently (do NOT repeat): {used}
Pick the ONE headline with the biggest hype potential (GTA 6 launches Nov 19, 2026 – prefer GTA 6 when there is
real news about it). Write a Short:
- 55–75 words, English, energetic but factual. First sentence = scroll-stopping hook (max 9 words).
- ONLY facts that are in the headline/news – never invent dates, prices, features or leaks. Say "reportedly" if the
  headline is a report/rumor.
- End with a question to viewers + "Follow for daily gaming news."
- 4 visuals: AI illustrations that capture the VIBE (e.g. "neon-lit Miami-style city at night, palm trees, sports car
  drifting, cinematic"). NEVER real game characters, celebrities, logos, brand names or text in the image.
Answer ONLY JSON: {{"headline": "...", "game": "...", "title": "max 70 chars, punchy, incl. game name, no hashtags",
 "text": "...", "visuals": ["prompt 1", "prompt 2", "prompt 3", "prompt 4"], "hashtags": ["gaming", "..."]}}"""


def used():
    try:
        return json.loads(USED.read_text())
    except Exception:  # noqa: BLE001
        return []


def news_short(out: Path, seed=None):
    rnd = random.Random(seed)
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=out))
    news = []
    for q in ["GTA 6", "Rockstar Games", "video game news", "PlayStation", "Xbox", "Nintendo Switch 2", "Steam game"]:
        news += wi.google_news(q + " when:2d", 5)
    news_txt = "\n".join(f"- {t}" for t, _ in news[:30])
    sc = gemini.ask_json(TASK.format(news=news_txt, used="; ".join(used()[-15:]) or "-"), temperature=0.8)
    print(f"  News: {sc.get('headline')}\n  → {sc.get('title')}")
    import modal
    from modal_app import ImageFlux, Voice, app, download_flux
    ref_path = ROOT / "data" / "voices" / "anime" / "narrator.wav"
    ref = ref_path.read_bytes() if ref_path.exists() else b""
    with modal.enable_output(), app.run():
        download_flux.remote()
        voice, img = Voice(), ImageFlux()
        a, subs = wi.narrate(voice, ref, wi.sentences(sc["text"]), work, "n")
        srcs = []
        for i, p in enumerate((sc.get("visuals") or [])[:4]):
            p = re.sub(r"(?i)\b(gta|grand theft auto|rockstar|jason|lucia)\b", "", str(p))
            png = img.generate.remote(f"cinematic video game concept art style, vibrant neon colors, dramatic lighting, "
                                      f"vertical composition. {p}. no text, no logos", seed=300 + i + rnd.randint(0, 999),
                                      width=928, height=1664, negative=NEGATIVE)
            src = work / f"ai_{i}.png"
            src.write_bytes(png)
            srcs.append(src)
    fade, total = 0.5, len(a) / SR
    per = total / max(1, len(srcs)) + fade
    clips = []
    for j, src in enumerate(srcs):
        dst = work / f"c{j}.mp4"
        wi.segment_video(src, dst, per, True, w=1080, h=1920, seed=j)
        clips.append(dst)
    wi.xfade_concat(clips, [per] * len(clips), work / "short.mp4", fade)
    wi.karaoke_ass(wi.word_times(a, subs), work / "s.ass", 1080, 1920, 92, 0, align=5, upper=True)
    wi.mix_and_render(work / "short.mp4", a, out / "gaming_short.mp4", work, work / "s.ass", music_db=-20)
    tags = [h.lstrip("#") for h in sc.get("hashtags", [])][:3]
    meta = {"title": f"{sc['title'][:90]} #shorts", "headline": sc.get("headline"),
            "description": f"{sc['text']}\n\nSource: {sc.get('headline')}\nImages are AI-generated illustrations, "
                           "not in-game footage.\n" + " ".join("#" + t for t in tags),
            "tags": tags + ["gaming", "gaming news", "shorts"]}
    (out / "gaming_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    subprocess.run(["rm", "-rf", str(work)])
    return meta


def publish(out: Path, meta):
    import upload
    yt = upload.service(os.environ[CFG["token_secret"]])
    ch = {"category_id": "20", "made_for_kids": False, "privacy": "public", "name": CFG["name"]}
    vid = upload.upload(yt, out / "gaming_short.mp4", meta, ch)
    print(f"  ✓ Short: https://youtu.be/{vid}")
    upload.mark_uploaded("gaming")
    u = used()
    u.append(meta.get("headline", ""))
    USED.write_text(json.dumps(u[-200:], ensure_ascii=False, indent=0))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output/gaming")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--seed", type=int)
    a = ap.parse_args()
    m = news_short(Path(a.out), a.seed)
    if a.publish:
        publish(Path(a.out), m)
