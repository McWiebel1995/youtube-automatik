#!/usr/bin/env python3
"""Leistung aller 6 Kanäle (öffentliche Zahlen der YouTube Data API): Abos, Aufrufe, je Video Views/Likes."""
import datetime as dt
import json
import os
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import upload  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
chans = list(yaml.safe_load(open(ROOT / "config/channels.yaml"))["channels"].values()) + \
        list(yaml.safe_load(open(ROOT / "config/kids.yaml"))["channels"].values()) + \
        [yaml.safe_load(open(ROOT / "config/whatif.yaml"))["channel"]]
now = dt.datetime.now(dt.timezone.utc)
report, data = [], {"at": now.isoformat(), "channels": []}
for ch in chans:
    try:
        yt = upload.service(os.environ[ch["token_secret"]])
        c = yt.channels().list(part="snippet,statistics,contentDetails", mine=True).execute()["items"][0]
        stt = c["statistics"]
        pl = c["contentDetails"]["relatedPlaylists"]["uploads"]
        ids = [i["contentDetails"]["videoId"] for i in
               yt.playlistItems().list(part="contentDetails", playlistId=pl, maxResults=25).execute().get("items", [])]
        vids = yt.videos().list(part="snippet,statistics,status,contentDetails", id=",".join(ids)).execute().get("items", []) if ids else []
        rows = []
        for v in vids:
            s = v["statistics"]
            pub = dt.datetime.fromisoformat(v["snippet"]["publishedAt"].replace("Z", "+00:00"))
            rows.append({"title": v["snippet"]["title"], "views": int(s.get("viewCount", 0)),
                         "likes": int(s.get("likeCount", 0)), "comments": int(s.get("commentCount", 0)),
                         "privacy": v["status"]["privacyStatus"], "duration": v["contentDetails"]["duration"],
                         "age_h": round((now - pub).total_seconds() / 3600), "id": v["id"]})
        data["channels"].append({"name": c["snippet"]["title"], "subs": int(stt.get("subscriberCount", 0)),
                                 "views": int(stt.get("viewCount", 0)), "videos": int(stt.get("videoCount", 0)), "list": rows})
        report.append(f"## {c['snippet']['title']}: {stt.get('subscriberCount')} Abos, {stt.get('viewCount')} Aufrufe, "
                      f"{stt.get('videoCount')} Videos")
        for r in sorted(rows, key=lambda r: -r["views"])[:8]:
            report.append(f"- {r['views']} Views, {r['likes']} Likes | {r['privacy']} | {r['duration']} | "
                          f"{r['age_h']} h alt | {r['title'][:60]}")
    except Exception as e:  # noqa: BLE001
        report.append(f"## {ch['name']}: FEHLER {str(e)[:200]}")
out = ROOT / "data" / "stats"
out.mkdir(parents=True, exist_ok=True)
(out / f"{now:%Y-%m-%d}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
print("\n".join(report))
print("::notice title=Statistik::" + " ⏎ ".join(report))
