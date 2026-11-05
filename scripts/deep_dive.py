#!/usr/bin/env python3
"""Tiefenanalyse eines Kanals (nur lesend) -> data/analytics/deep_<key>.json
Tagesverlauf (Aufrufe, Wiedergabezeit, Abos), Zuschauerquellen pro Tag, pro Video Aufrufe/Anteil/Abos/Likes."""
import datetime as dt
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "anime")]
import analytics_report as ar  # noqa: E402

KEY = os.environ.get("CH", "whatif")
DAYS = int(os.environ.get("DAYS", "28"))
key, name, secret = next(c for c in ar.yt_channels() if c[0] == KEY)
from googleapiclient.discovery import build  # noqa: E402
c = ar.creds(os.environ[secret])
ya = build("youtubeAnalytics", "v2", credentials=c, cache_discovery=False)
end = dt.date.today()
start = (end - dt.timedelta(days=DAYS)).isoformat()
out = {"channel": name, "start": start, "end": end.isoformat(), "errors": []}


def q(**kw):
    try:
        r = ya.reports().query(ids="channel==MINE", startDate=start, endDate=end.isoformat(), **kw).execute()
        cols = [h["name"] for h in r["columnHeaders"]]
        return [dict(zip(cols, row)) for row in r.get("rows", [])]
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"{kw.get('metrics')}/{kw.get('dimensions')}: {str(e)[:200]}")
        return []


out["daily"] = q(metrics="views,estimatedMinutesWatched,averageViewPercentage,subscribersGained,likes", dimensions="day", sort="day")
out["daily_traffic"] = q(metrics="views", dimensions="day,insightTrafficSourceType", sort="day")
out["videos"] = q(metrics="views,averageViewPercentage,averageViewDuration,subscribersGained,likes,shares,comments",
                  dimensions="video", sort="-views", maxResults=200)
out["video_daily"] = q(metrics="views", dimensions="day,video", sort="day", maxResults=200) if False else []
yt = build("youtube", "v3", credentials=c, cache_discovery=False)
ids = [v["video"] for v in out["videos"]][:150]
meta = {}
for k in range(0, len(ids), 50):
    for v in yt.videos().list(part="snippet,contentDetails,statistics", id=",".join(ids[k:k + 50])).execute().get("items", []):
        meta[v["id"]] = {"title": v["snippet"]["title"], "published": v["snippet"]["publishedAt"],
                         "dur": v["contentDetails"]["duration"], "views_now": int(v["statistics"].get("viewCount", 0))}
for v in out["videos"]:
    v.update(meta.get(v["video"], {}))
Path("data/analytics").mkdir(parents=True, exist_ok=True)
Path(f"data/analytics/deep_{KEY}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"::notice title=Tiefenanalyse::{name}: {len(out['daily'])} Tage, {len(out['videos'])} Videos, Fehler: {out['errors']}")
