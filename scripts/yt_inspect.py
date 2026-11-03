#!/usr/bin/env python3
"""Zeigt Titel, Hashtags in der Beschreibung und Stichwörter der letzten Videos je Kanal (nur lesend)."""
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "anime")]
import analytics_report  # noqa: E402
import upload  # noqa: E402

N = int(os.environ.get("N", "3"))
out = []
for key, name, secret in analytics_report.yt_channels():
    if not os.environ.get(secret):
        continue
    try:
        yt = upload.service(os.environ[secret])
        pl = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        ids = [i["contentDetails"]["videoId"] for i in yt.playlistItems().list(part="contentDetails", playlistId=pl, maxResults=N).execute()["items"]]
        for v in yt.videos().list(part="snippet", id=",".join(ids)).execute()["items"]:
            sn = v["snippet"]
            tags_in_desc = re.findall(r"(?<!\w)#[\wäöüÄÖÜß]+", sn.get("description", ""))
            out.append(f"{name} | {sn['publishedAt'][:16]} | {sn['title'][:60]} | Hashtags Beschreibung ({len(tags_in_desc)}): "
                       f"{' '.join(tags_in_desc)} | Stichwörter: {len(sn.get('tags', []))} | Anfang: {sn.get('description', '')[:90]!r}")
    except Exception as e:  # noqa: BLE001
        out.append(f"{name}: {str(e)[:150]}")
print("\n".join(out))
for k in range(0, len(out), 6):
    print(f"::notice title=Videos {k // 6 + 1}::{' ⏎ '.join(out[k:k + 6])[:3900]}")
