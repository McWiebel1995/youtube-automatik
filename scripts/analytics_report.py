#!/usr/bin/env python3
"""
Leistungsdaten aller Kanäle sammeln (nur lesend) -> data/analytics/report.json

YouTube (Data API + Analytics API): pro Video Aufrufe, Wiedergabezeit, durchschnittlich angesehener Anteil,
neue Abos, Likes, Shares, Impressionen/Klickrate (falls verfügbar), Uhrzeit, Länge, Titel.
Instagram: pro Reel/Karussell Likes, Kommentare, Reichweite, Aufrufe, Saves, Shares (falls Insights erlaubt).
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
OUT = ROOT / "data" / "analytics" / "report.json"
DAYS = 60


def yt_channels():
    relax = yaml.safe_load(open(ROOT / "config/channels.yaml"))["channels"]
    kids = yaml.safe_load(open(ROOT / "config/kids.yaml"))["channels"]
    wi = yaml.safe_load(open(ROOT / "config/whatif.yaml"))["channel"]
    out = [(k, c["name"], c["token_secret"]) for k, c in relax.items()]
    out += [(k, c["name"], c["token_secret"]) for k, c in kids.items()]
    out += [("whatif", wi["name"], wi["token_secret"]), ("gedanken", "Ruhige Gedanken", "YT_REFRESH_TOKEN_GEDANKEN")]
    return out


def creds(tok):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    c = Credentials(None, refresh_token=tok, client_id=os.environ["YT_CLIENT_ID"],
                    client_secret=os.environ["YT_CLIENT_SECRET"], token_uri="https://oauth2.googleapis.com/token")
    c.refresh(Request())
    return c


def secs(iso):
    import re
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    return 0 if not m else int(m[1] or 0) * 3600 + int(m[2] or 0) * 60 + int(m[3] or 0)


def yt_channel(key, name, secret, start, end):
    from googleapiclient.discovery import build
    c = creds(os.environ[secret])
    yt = build("youtube", "v3", credentials=c, cache_discovery=False)
    ya = build("youtubeAnalytics", "v2", credentials=c, cache_discovery=False)
    ch = yt.channels().list(part="contentDetails,statistics,snippet,status", mine=True).execute()["items"][0]
    pl = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, tok = [], None
    while True:
        r = yt.playlistItems().list(part="contentDetails", playlistId=pl, maxResults=50, pageToken=tok).execute()
        new = r.get("items", [])
        ids += [i["contentDetails"]["videoId"] for i in new]
        tok = r.get("nextPageToken")
        if not tok or (new and new[-1]["contentDetails"].get("videoPublishedAt", "9") < start) or len(ids) > 400:
            break
    vids = {}
    for k in range(0, len(ids), 50):
        for v in yt.videos().list(part="snippet,contentDetails,statistics,status", id=",".join(ids[k:k + 50])).execute()["items"]:
            if v["snippet"]["publishedAt"][:10] < start:
                continue
            st = v.get("statistics", {})
            vids[v["id"]] = {"id": v["id"], "title": v["snippet"]["title"], "published": v["snippet"]["publishedAt"],
                             "seconds": secs(v["contentDetails"]["duration"]), "privacy": v["status"].get("privacyStatus"),
                             "views": int(st.get("viewCount", 0)), "likes": int(st.get("likeCount", 0)),
                             "comments": int(st.get("commentCount", 0)),
                             "tags": v["snippet"].get("tags", [])[:10], "has_desc": len(v["snippet"].get("description", ""))}
    res = {"key": key, "name": name, "subs": int(ch["statistics"].get("subscriberCount", 0)),
           "views_total": int(ch["statistics"].get("viewCount", 0)),
           "made_for_kids": ch.get("status", {}).get("madeForKids"), "videos": list(vids.values()), "errors": []}

    def q(metrics, dims="video", extra=None):
        try:
            return ya.reports().query(ids="channel==MINE", startDate=start, endDate=end, metrics=metrics,
                                      dimensions=dims, maxResults=200, sort="-views" if "views" in metrics else None,
                                      **(extra or {})).execute()
        except Exception as e:  # noqa: BLE001
            res["errors"].append(f"{metrics[:40]}: {str(e)[:160]}")
            return None

    r = q("views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained,likes,shares")
    if r:
        cols = [h["name"] for h in r["columnHeaders"]]
        for row in r.get("rows", []):
            d = dict(zip(cols, row))
            if d["video"] in vids:
                vids[d["video"]].update({k: d[k] for k in cols if k != "video" and k != "views"}, a_views=d["views"])
    r = q("videoThumbnailImpressions,videoThumbnailImpressionsClickRate", extra={"sort": "-videoThumbnailImpressions"})
    if r:
        cols = [h["name"] for h in r["columnHeaders"]]
        for row in r.get("rows", []):
            d = dict(zip(cols, row))
            if d["video"] in vids:
                vids[d["video"]].update(impressions=d["videoThumbnailImpressions"], ctr=d["videoThumbnailImpressionsClickRate"])
    for dims, label in (("insightTrafficSourceType", "traffic"), ("country", "countries"), ("ageGroup", "age"),
                        ("creatorContentType", "content_type")):
        metrics = "viewerPercentage" if dims == "ageGroup" else "views,estimatedMinutesWatched"
        r = q(metrics, dims, {"sort": None if dims == "ageGroup" else "-views"})
        if r:
            cols = [h["name"] for h in r["columnHeaders"]]
            res[label] = [dict(zip(cols, row)) for row in r.get("rows", [])][:15]
    r = q("views,subscribersGained", "day", {"sort": "day"})
    if r:
        res["daily"] = [dict(zip([h["name"] for h in r["columnHeaders"]], row)) for row in r.get("rows", [])]
    res["videos"] = list(vids.values())
    return res


def ig_account(key):
    import instagram
    tok = instagram.token_for(key)
    me = instagram._req("GET", "me", tok, fields="username,followers_count,media_count")
    media, after = [], None
    for _ in range(4):
        kw = {"fields": "id,caption,timestamp,media_type,media_product_type,like_count,comments_count,permalink", "limit": 50}
        if after:
            kw["after"] = after
        js = instagram._req("GET", "me/media", tok, **kw)
        media += js.get("data", [])
        after = (js.get("paging") or {}).get("cursors", {}).get("after")
        if not after:
            break
    errs = []
    for m in media[:80]:
        mt = "reach,views,saved,shares,total_interactions" + (",ig_reels_avg_watch_time" if m.get("media_product_type") == "REELS" else "")
        try:
            ins = instagram._req("GET", f"{m['id']}/insights", tok, metric=mt).get("data", [])
            m["insights"] = {i["name"]: (i.get("values") or [{}])[0].get("value", i.get("total_value", {}).get("value"))
                             for i in ins}
        except Exception as e:  # noqa: BLE001
            if len(errs) < 2:
                errs.append(str(e)[:200])
        m["caption"] = (m.get("caption") or "")[:200]
    return {"key": key, "username": me.get("username"), "followers": me.get("followers_count"),
            "posts": me.get("media_count"), "media": media, "errors": errs}


def main():
    end = dt.date.today()
    start = (end - dt.timedelta(days=DAYS)).isoformat()
    rep = {"generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "start": start,
           "end": end.isoformat(), "youtube": [], "instagram": []}
    for key, name, secret in yt_channels():
        if not os.environ.get(secret):
            continue
        try:
            rep["youtube"].append(yt_channel(key, name, secret, start, end.isoformat()))
            print(f"✓ YT {name}: {len(rep['youtube'][-1]['videos'])} Videos")
        except Exception as e:  # noqa: BLE001
            rep["youtube"].append({"key": key, "name": name, "error": str(e)[:300]})
            print(f"✗ YT {name}: {e}")
    import instagram
    for key in instagram.ACCOUNTS:
        try:
            rep["instagram"].append(ig_account(key))
            print(f"✓ IG {key}: {len(rep['instagram'][-1]['media'])} Beiträge")
        except Exception as e:  # noqa: BLE001
            rep["instagram"].append({"key": key, "error": str(e)[:300]})
            print(f"✗ IG {key}: {e}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    errs = [f"{c['name']}: {c.get('error') or '; '.join(c.get('errors', []))}" for c in rep["youtube"]
            if c.get("error") or c.get("errors")]
    errs += [f"IG {c['key']}: {c.get('error') or '; '.join(c.get('errors', []))}" for c in rep["instagram"]
             if c.get("error") or c.get("errors")]
    print(f"::notice title=Analytics::{len(rep['youtube'])} YT-Kanäle, {len(rep['instagram'])} IG-Konten"
          + (" ⏎ " + " ⏎ ".join(errs) if errs else "")[:3800])


if __name__ == "__main__":
    main()
