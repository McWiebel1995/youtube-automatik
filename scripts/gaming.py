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


PRESS_PREFIX = "press-"            # GitHub-Releases "press-<spiel>" mit freigegebenen Pressevideos + license.txt


def press_footage(game, work: Path):
    """Freigegebenes Pressevideo zum Spiel holen (aus Release 'press-<slug>'). -> (Pfad, Hinweistext) oder (None, None).
    license.txt im Release: 1. Zeile = Hersteller/Copyright, 2. Zeile = Quelle/Bedingungen."""
    repo = os.environ.get("GITHUB_REPOSITORY", "McWiebel1995/youtube-automatik")
    try:
        rels = json.loads(subprocess.run(["gh", "api", f"repos/{repo}/releases?per_page=100"], capture_output=True,
                                         text=True).stdout or "[]")
    except Exception:  # noqa: BLE001
        return None, None
    words = set(re.findall(r"[a-z0-9]+", (game or "").lower()))
    best = None
    for r in rels:
        tag = r.get("tag_name", "")
        if not tag.startswith(PRESS_PREFIX):
            continue
        tw = set(tag[len(PRESS_PREFIX):].split("-"))
        score = len(words & tw)
        if score and (not best or score > best[0]):
            best = (score, r)
    if not best:
        return None, None
    r = best[1]
    vids = [a for a in r.get("assets", []) if a["name"].lower().endswith((".mp4", ".mov", ".webm", ".mkv"))]
    lic = next((a for a in r.get("assets", []) if a["name"].lower() == "license.txt"), None)
    if not vids or not lic:                           # ohne Freigabe-Notiz wird nichts verwendet
        print(f"  ⚠ Pressematerial {r['tag_name']}: kein Video oder keine license.txt – übersprungen")
        return None, None
    d = work / "press"
    d.mkdir(exist_ok=True)
    pick = random.choice(vids)
    for a in (pick, lic):
        subprocess.run(["gh", "release", "download", r["tag_name"], "--repo", repo, "-p", a["name"], "-D", str(d), "--clobber"],
                       capture_output=True)
    note = (d / "license.txt").read_text(encoding="utf-8", errors="ignore").strip().splitlines() if (d / "license.txt").exists() else []
    src = d / pick["name"]
    return (src if src.exists() else None), (note[0] if note else r["tag_name"])


def press_segments(src: Path, work: Path, n, seconds, rnd):
    """n stumme, hochkant zugeschnittene Ausschnitte (je `seconds` s) aus verschiedenen Stellen des Pressevideos."""
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(src)],
                               capture_output=True, text=True).stdout or 0)
    out = []
    if dur < seconds + 2:
        return out
    starts = sorted(rnd.uniform(1, dur - seconds - 1) for _ in range(n))
    for k, st in enumerate(starts):
        dst = work / f"p{k}.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{st:.2f}", "-i", str(src), "-t", f"{seconds:.2f}", "-an",
                        "-vf", "scale=-2:1920,crop=1080:1920,setsar=1,fps=30", "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "20", "-pix_fmt", "yuv420p", str(dst)], capture_output=True)
        if dst.exists():
            out.append(dst)
    return out


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
    credit = None
    pv, credit = press_footage(sc.get("game"), work)  # freigegebenes Pressevideo: max. ~40 %, ohne Originalton
    if pv:
        segs = press_segments(pv, work, n=2, seconds=per, rnd=rnd)
        for k, sg in enumerate(segs):                 # ersetzt jedes 2. KI-Bild
            idx = 1 + 2 * k
            if idx < len(clips):
                clips[idx] = sg
        print(f"  🎞 Pressematerial: {len(segs)} Ausschnitte ({credit})")
    wi.xfade_concat(clips, [per] * len(clips), work / "short.mp4", fade)
    wi.karaoke_ass(wi.word_times(a, subs), work / "s.ass", 1080, 1920, 92, 0, align=5, upper=True)
    wi.mix_and_render(work / "short.mp4", a, out / "gaming_short.mp4", work, work / "s.ass", music_db=-20)
    tags = [h.lstrip("#") for h in sc.get("hashtags", [])][:3]
    meta = {"title": f"{sc['title'][:90]} #shorts", "headline": sc.get("headline"),
            "description": f"{sc['text']}\n\nSource: {sc.get('headline')}\n" +
                           (f"Footage: {credit} – official press material, used for news coverage.\n" if credit else "") +
                           "Other images are AI-generated illustrations, not in-game footage.\n" + " ".join("#" + t for t in tags),
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
