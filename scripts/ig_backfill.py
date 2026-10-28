#!/usr/bin/env python3
"""
Ältere YouTube-Shorts von Beyond the If nach und nach auf Instagram (facts_mcwiebel) bringen.

  python scripts/ig_backfill.py --list        # zeigt, was noch nachgeholt wird
  python scripts/ig_backfill.py --post 1      # postet das nächste (1 pro Lauf, täglich)

Reihenfolge: zeitlose Shorts (Quiz, What-if) zuerst, neueste zuerst. News älter als NEWS_MAX_DAYS werden
übersprungen (veraltete Nachrichten wirken auf Instagram falsch). Merkt sich alles in data/ig_backfill/whatif.json.
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
STATE = ROOT / "data" / "ig_backfill" / "whatif.json"
NEWS_MAX_DAYS = 5
SECRET = "YT_REFRESH_TOKEN_WHATIF"


def load():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save(st):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def secs(iso):
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    return 0 if not m else int(m[1] or 0) * 3600 + int(m[2] or 0) * 60 + int(m[3] or 0)


def kind(v):
    t = (v["title"] + " " + v["desc"]).lower()
    if "quiz" in t or re.search(r"\b(guess|can you get|test yourself)\b", t):
        return "quiz"
    if re.search(r"\b(news|breaking|today|this week|announced|just)\b", t):
        return "news"
    return "short"


def shorts():
    import upload
    yt = upload.service(os.environ[SECRET])
    ch = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
    pl, ids, tok = ch["contentDetails"]["relatedPlaylists"]["uploads"], [], None
    while True:
        r = yt.playlistItems().list(part="contentDetails", playlistId=pl, maxResults=50, pageToken=tok).execute()
        ids += [i["contentDetails"]["videoId"] for i in r.get("items", [])]
        tok = r.get("nextPageToken")
        if not tok or len(ids) >= 300:
            break
    out = []
    for k in range(0, len(ids), 50):
        for v in yt.videos().list(part="snippet,contentDetails,status", id=",".join(ids[k:k + 50])).execute()["items"]:
            if v["status"].get("privacyStatus") != "public" or secs(v["contentDetails"]["duration"]) > 180:
                continue
            out.append({"id": v["id"], "title": v["snippet"]["title"], "desc": v["snippet"].get("description", ""),
                        "date": v["snippet"]["publishedAt"]})
    for v in out:
        v["kind"] = kind(v)
    return out


def ig_titles():
    """Bereits auf Instagram vorhandene Reels (erste Caption-Zeile) – nichts doppelt posten."""
    import instagram
    try:
        js = instagram._req("GET", "me/media", instagram.token_for("whatif"), fields="caption", limit=50)
        return {(m.get("caption") or "").split("\n")[0].strip().lower()[:60] for m in js.get("data", [])}
    except Exception:  # noqa: BLE001
        return set()


def todo(st):
    now = dt.datetime.now(dt.timezone.utc)
    have = ig_titles()
    res = []
    for v in shorts():
        if st.get(v["id"], {}).get("status") in ("posted", "failed"):
            continue
        age = (now - dt.datetime.fromisoformat(v["date"].replace("Z", "+00:00"))).days
        if age < 1:                                   # ganz neue kommen über den normalen Weg
            continue
        if v["kind"] == "news" and age > NEWS_MAX_DAYS:
            continue
        if re.sub(r"#\w+", "", v["title"]).strip().lower()[:60] in have:
            continue
        res.append(v)
    # frische News zuerst (verfallen sonst), dann Quiz/What-if-Shorts, jeweils neueste zuerst
    news = [v for v in res if v["kind"] == "news"]
    rest = sorted([v for v in res if v["kind"] != "news"], key=lambda v: v["date"], reverse=True)
    return sorted(news, key=lambda v: v["date"], reverse=True) + rest


def download(vid, work: Path):
    work.mkdir(parents=True, exist_ok=True)
    out = work / f"{vid}.mp4"
    cmd = ["yt-dlp", "-q", "--no-warnings", "-f", "bv*[ext=mp4][height<=1920]+ba[ext=m4a]/b[ext=mp4]/b",
           "--merge-output-format", "mp4", "-o", str(out), f"https://www.youtube.com/shorts/{vid}"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode or not out.exists():
        raise RuntimeError("Download fehlgeschlagen: " + (r.stderr or r.stdout)[-300:])
    return out


def post_one(v):
    import hashtags
    import ig_queue
    import instagram
    work = ROOT / "output" / "ig_backfill"
    mp4 = download(v["id"], work)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    url = ig_queue.upload_public(mp4, f"whatif-bf-{stamp}.mp4")
    cover = ig_queue.make_cover(mp4)
    cover_url = ig_queue.upload_public(cover, f"whatif-bf-{stamp}-cover.jpg") if cover else None
    title = re.sub(r"#\w+", "", v["title"]).strip()
    body = re.sub(r"(?im)^.*(subscribe|youtube\.com|youtu\.be).*$", "", v["desc"]).strip()
    caption = hashtags.ig_caption(f"{title}\n\n{body}"[:2000], "whatif")
    return instagram.publish_reel("whatif", url, caption, cover_url=cover_url)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--post", type=int, default=0)
    a = ap.parse_args()
    st = load()
    items = todo(st)
    lines = [f"{len(items)} Shorts warten auf Instagram"] + [f"{v['date'][:10]} [{v['kind']}] {v['title'][:70]}"
                                                          for v in items[:30]]
    print("\n".join(lines))
    if a.list:
        print(f"::notice title=Nachholen facts_mcwiebel::{' ⏎ '.join(lines)[:3800]}")
        return
    report = []
    for v in items[:a.post]:
        try:
            mid, link = post_one(v)
            st[v["id"]] = {"status": "posted", "at": dt.datetime.now().isoformat(timespec="seconds"), "ig": link}
            report.append(f"✅ {v['title'][:60]} → {link}")
        except Exception as e:  # noqa: BLE001
            prev = st.get(v["id"], {})
            tries = prev.get("tries", 0) + 1
            st[v["id"]] = {"status": "failed" if tries >= 3 else "retry", "tries": tries, "error": str(e)[:300]}
            report.append(f"❌ {v['title'][:60]}: {str(e)[:200]}")
    save(st)
    msg = " | ".join(report) or "nichts gepostet"
    print(msg)
    print(f"::notice title=Nachholen facts_mcwiebel::{msg} · noch {max(0, len(items) - a.post)} offen")


if __name__ == "__main__":
    main()
