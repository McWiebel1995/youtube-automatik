#!/usr/bin/env python3
"""Langen Beyond-the-If-Videos nachträglich ein Thumbnail im neuen Stil geben (Stockfoto + thumbs.whatif).

  python scripts/thumb_redo.py --days 14        # alle langen Videos der letzten 14 Tage
"""
import argparse
import datetime as dt
import json
import os
import random
import re
import sys
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT / "anime")]
OUT = ROOT / "output" / "thumb_redo"
DONE = ROOT / "data" / "thumb_redo.json"


def secs(iso):
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    return 0 if not m else int(m[1] or 0) * 3600 + int(m[2] or 0) * 60 + int(m[3] or 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    a = ap.parse_args()
    import covers
    import gemini
    import thumbs
    import upload
    OUT.mkdir(parents=True, exist_ok=True)
    done = json.loads(DONE.read_text()) if DONE.exists() else []
    yt = upload.service(os.environ["YT_REFRESH_TOKEN_WHATIF"])
    ch = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
    pl = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    ids = [i["contentDetails"]["videoId"] for i in
           yt.playlistItems().list(part="contentDetails", playlistId=pl, maxResults=50).execute()["items"]]
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=a.days)).isoformat()
    report = []
    for v in yt.videos().list(part="snippet,contentDetails", id=",".join(ids)).execute()["items"]:
        if secs(v["contentDetails"]["duration"]) <= 180 or v["snippet"]["publishedAt"] < since[:19] or v["id"] in done:
            continue
        title = v["snippet"]["title"]
        js = gemini.ask_json(
            f"YouTube video title: '{title}'. Give (1) 2–4 punchy ALL-CAPS thumbnail words that do NOT start with "
            "'What if' (e.g. 'EARTH STOPS SPINNING'), (2) a 2–4 word English stock-photo search query for ONE "
            "dramatic, clearly visible subject (space, nature, science), no people. "
            'JSON: {"text": "...", "query": "..."}', temperature=0.4)
        cands = covers._pexels(js["query"], "landscape") or covers._pixabay(js["query"], "landscape", "photo")
        if not cands:
            report.append(f"❌ {title}: kein Bild für „{js['query']}“")
            continue
        bg = OUT / f"{v['id']}_bg.jpg"
        bg.write_bytes(requests.get(random.choice(cands[:4])[1], timeout=60).content)
        th = thumbs.whatif(bg, js["text"], OUT / f"{v['id']}.jpg")
        if upload.set_thumbnail(yt, v["id"], th):
            done.append(v["id"])
            report.append(f"✅ {title} → „{js['text']}“")
        else:
            report.append(f"❌ {title}: Hochladen fehlgeschlagen")
    DONE.write_text(json.dumps(done, indent=0))
    print("\n".join(report) or "nichts zu tun")
    print(f"::notice title=Thumbnails::{' ⏎ '.join(report) or 'nichts zu tun'}")


if __name__ == "__main__":
    main()
