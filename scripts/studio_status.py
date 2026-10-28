#!/usr/bin/env python3
"""Sammelt den Stand aller Kanäle für das virtuelle Studio (GitHub Pages) -> site/status.json.

Nur lesend: YouTube (Abos, Aufrufe, letzte Videos), Instagram (Follower, letzte Reels), Upload-Sperren, IG-Warteschlange.
Keine Tokens oder Secrets landen in der Datei.
"""
import datetime as dt
import json
import os
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import upload  # noqa: E402

OUT = ROOT / "site" / "status.json"

# Studio-Räume: Schlüssel -> (Konfig, Upload-Sperren-Schlüssel, Instagram-Konto)
def channels():
    relax = yaml.safe_load(open(ROOT / "config/channels.yaml"))["channels"]
    kids = yaml.safe_load(open(ROOT / "config/kids.yaml"))["channels"]
    wi = yaml.safe_load(open(ROOT / "config/whatif.yaml"))["channel"]
    out = []
    for k, c in relax.items():
        out.append({"key": k, "group": "relax", "cfg": c, "locks": [k], "ig": "calmhaven"})
    for k, c in kids.items():
        out.append({"key": k, "group": "kids", "cfg": c, "locks": ["kids-" + k],
                    "ig": {"schlaf": "mondmelodie", "lernen": "lernbaerchen", "geschichten": "gutenacht"}.get(k)})
    out.append({"key": "whatif", "group": "whatif", "cfg": wi, "locks": ["whatif", "whatif-news", "whatif-quiz"],
                "ig": "whatif"})
    return out


def yt_info(ch, n=6):
    yt = upload.service(os.environ[ch["cfg"]["token_secret"]])
    c = yt.channels().list(part="contentDetails,snippet,statistics", mine=True).execute()["items"][0]
    pl = c["contentDetails"]["relatedPlaylists"]["uploads"]
    items = yt.playlistItems().list(part="contentDetails", playlistId=pl, maxResults=n).execute().get("items", [])
    ids = [i["contentDetails"]["videoId"] for i in items]
    vids = yt.videos().list(part="snippet,status,contentDetails,statistics", id=",".join(ids)).execute().get("items", []) \
        if ids else []
    st = c.get("statistics", {})
    return {
        "title": c["snippet"]["title"],
        "url": f"https://www.youtube.com/channel/{c['id']}",
        "avatar": c["snippet"]["thumbnails"].get("default", {}).get("url", ""),
        "subs": int(st.get("subscriberCount", 0)), "views": int(st.get("viewCount", 0)),
        "videos_total": int(st.get("videoCount", 0)),
        "videos": [{
            "id": v["id"], "title": v["snippet"]["title"],
            "uploaded": v["snippet"]["publishedAt"],
            "privacy": v["status"].get("privacyStatus"), "publish_at": v["status"].get("publishAt"),
            "duration": v["contentDetails"].get("duration"),
            "views": int(v.get("statistics", {}).get("viewCount", 0)),
            "likes": int(v.get("statistics", {}).get("likeCount", 0)),
            "thumb": (v["snippet"]["thumbnails"].get("medium") or v["snippet"]["thumbnails"].get("default") or {}).get("url", ""),
        } for v in sorted(vids, key=lambda v: v["snippet"]["publishedAt"], reverse=True)],
    }


def ig_info(account, n=4):
    import instagram
    if account not in instagram.ACCOUNTS:
        return None
    tok = instagram.token_for(account)
    me = instagram._req("GET", "me", tok, fields="username,followers_count,media_count")
    md = instagram._req("GET", "me/media", tok, fields="caption,media_type,permalink,timestamp,thumbnail_url,media_url",
                        limit=n).get("data", [])
    return {"username": me.get("username"), "followers": me.get("followers_count"), "posts": me.get("media_count"),
            "media": [{"caption": (m.get("caption") or "").split("\n")[0][:90], "url": m.get("permalink"),
                       "time": m.get("timestamp"), "thumb": m.get("thumbnail_url") or m.get("media_url")} for m in md]}


def main():
    today = dt.date.today().isoformat()
    locks = {p.stem: p.read_text().strip() for p in (ROOT / "data/last_upload").glob("*.txt")}
    queue = [json.loads(p.read_text()) for p in (ROOT / "data/ig_queue").glob("*.json")]
    res = {"generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "today": today,
           "channels": [], "instagram": {}}
    ig_cache = {}
    for ch in channels():
        e = {"key": ch["key"], "group": ch["group"], "name": ch["cfg"]["name"], "ig": ch["ig"],
             "last_upload": max([locks.get(k, "") for k in ch["locks"]] or [""]),
             "uploads_today": [k for k in ch["locks"] if locks.get(k) == today]}
        try:
            e["yt"] = yt_info(ch)
        except Exception as ex:  # noqa: BLE001
            e["yt_error"] = str(ex)[:160]
        res["channels"].append(e)
        if ch["ig"] and ch["ig"] not in ig_cache:
            try:
                ig_cache[ch["ig"]] = ig_info(ch["ig"])
            except Exception as ex:  # noqa: BLE001
                ig_cache[ch["ig"]] = {"error": str(ex)[:160]}
    for acc, info in ig_cache.items():
        if info is None:
            continue
        q = [x for x in queue if x.get("account") == acc]
        info["queue_pending"] = sum(1 for x in q if x.get("status") == "pending")
        last = max((x for x in q if x.get("status") == "posted"), key=lambda x: x.get("posted_at") or x["created_at"],
                   default=None)
        info["last_posted"] = (last or {}).get("posted_at") or (last or {}).get("created_at")
        res["instagram"][acc] = info
    # Zeitpläne der Workflows (für "nächster Lauf" im Studio)
    res["schedules"] = {}
    for wf in (ROOT / ".github/workflows").glob("*.yml"):
        y = yaml.safe_load(wf.read_text(encoding="utf-8"))
        on = y.get(True) or y.get("on") or {}
        crons = [c["cron"] for c in (on.get("schedule") or [])] if isinstance(on, dict) else []
        res["schedules"][wf.name] = {"name": y.get("name", wf.stem), "crons": crons}
    # Kommentar-Vorschläge zur Freigabe (öffentliche Kommentare, keine Zugangsdaten)
    try:
        pend = json.loads((ROOT / "data/comment_bot/pending.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pend = []
    (OUT.parent / "comments.json").write_text(json.dumps(
        {"generated": res["generated"], "items": [{k: v for k, v in e.items() if k != "acct"} for e in pend]},
        ensure_ascii=False, indent=1), encoding="utf-8")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✓ {OUT} ({len(res['channels'])} Kanäle, {len(res['instagram'])} IG-Konten)")


if __name__ == "__main__":
    main()
