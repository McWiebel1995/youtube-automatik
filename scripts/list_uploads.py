#!/usr/bin/env python3
"""Zeigt die letzten Uploads aller 6 Kanäle (Titel, Datum, Status, Länge, Verarbeitung) – ohne etwas zu ändern."""
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
n = int(os.environ.get("N", "6"))
out = []
for ch in chans:
    try:
        yt = upload.service(os.environ[ch["token_secret"]])
        c = yt.channels().list(part="contentDetails,snippet", mine=True).execute()["items"][0]
        pl = c["contentDetails"]["relatedPlaylists"]["uploads"]
        items = yt.playlistItems().list(part="contentDetails", playlistId=pl, maxResults=n).execute().get("items", [])
        ids = [i["contentDetails"]["videoId"] for i in items]
        vids = yt.videos().list(part="snippet,status,contentDetails,processingDetails", id=",".join(ids)).execute().get("items", []) if ids else []
        out.append(f"## {c['snippet']['title']}: {len(vids)} Videos")
        for v in vids:
            st, pd = v["status"], v.get("processingDetails", {})
            out.append(f"- {v['snippet']['publishedAt'][:16]} | {st.get('privacyStatus')}"
                       f"{' (geplant ' + st['publishAt'][:16] + ')' if st.get('publishAt') else ''} | "
                       f"{v['contentDetails'].get('duration')} | Upload {st.get('uploadStatus')}"
                       f"{'/' + st.get('rejectionReason', '') if st.get('rejectionReason') else ''}"
                       f"{'/' + st.get('failureReason', '') if st.get('failureReason') else ''} | "
                       f"Verarb. {pd.get('processingStatus', '?')} | {v['snippet']['title'][:70]}")
    except Exception as e:  # noqa: BLE001
        out.append(f"## {ch['name']}: FEHLER {str(e)[:200]}")
print("\n".join(out))
print("::notice title=Uploads::" + " ⏎ ".join(out))
