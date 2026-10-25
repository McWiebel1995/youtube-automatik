#!/usr/bin/env python3
"""Setzt die YouTube-Kennzeichnung „Veränderte oder synthetische Inhalte“ für bereits hochgeladene, automatisch
erzeugte Videos (ab Okt. 2026) der Kanäle mit KI-Erzählstimme bzw. realistischen KI-Szenen. Ändert sonst nichts."""
import os
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import upload  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SINCE = "2026-10-01"
kids = yaml.safe_load(open(ROOT / "config/kids.yaml"))["channels"]
chans = [kids["lernen"], kids["geschichten"], yaml.safe_load(open(ROOT / "config/whatif.yaml"))["channel"]]
report = []
for ch in chans:
    yt = upload.service(os.environ[ch["token_secret"]])
    c = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
    pl = c["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, tok = [], None
    while True:
        r = yt.playlistItems().list(part="contentDetails", playlistId=pl, maxResults=50, pageToken=tok).execute()
        ids += [i["contentDetails"]["videoId"] for i in r.get("items", [])
                if i["contentDetails"].get("videoPublishedAt", "9") >= SINCE]
        tok = r.get("nextPageToken")
        if not tok:
            break
    done = 0
    for k in range(0, len(ids), 50):
        for v in yt.videos().list(part="status", id=",".join(ids[k:k + 50])).execute().get("items", []):
            st = v["status"]
            if st.get("containsSyntheticMedia"):
                continue
            body = {k2: st[k2] for k2 in ("privacyStatus", "embeddable", "license", "publicStatsViewable",
                                          "selfDeclaredMadeForKids", "publishAt") if k2 in st}
            body["containsSyntheticMedia"] = True
            yt.videos().update(part="status", body={"id": v["id"], "status": body}).execute()
            done += 1
    report.append(f"{ch['name']}: {done} von {len(ids)} Videos gekennzeichnet")
print("\n".join(report))
print("::notice title=KI-Kennzeichnung::" + " | ".join(report))
