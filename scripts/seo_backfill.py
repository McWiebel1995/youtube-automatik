#!/usr/bin/env python3
"""Lange Videos der letzten X Tage nachträglich suchoptimieren (Beschreibung + Stichwörter; Titel/Video bleiben).

  python scripts/seo_backfill.py --days 30 [--dry-run]
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT / "anime")]
DONE = ROOT / "data" / "seo_done.json"


def secs(iso):
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    return 0 if not m else int(m[1] or 0) * 3600 + int(m[2] or 0) * 60 + int(m[3] or 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--shorts", action="store_true", help="auch Shorts")
    a = ap.parse_args()
    import analytics_report
    import hashtags
    import upload
    done = set(json.loads(DONE.read_text())) if DONE.exists() else set()
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=a.days)).isoformat()[:19]
    report, n_ok = [], 0
    for key, name, secret in analytics_report.yt_channels():
        if not os.environ.get(secret):
            continue
        try:
            yt = upload.service(os.environ[secret])
            pl = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]["contentDetails"][
                "relatedPlaylists"]["uploads"]
            ids = [i["contentDetails"]["videoId"] for i in
                   yt.playlistItems().list(part="contentDetails", playlistId=pl, maxResults=50).execute()["items"]]
            vids = yt.videos().list(part="snippet,contentDetails", id=",".join(ids)).execute()["items"] if ids else []
        except Exception as e:  # noqa: BLE001
            report.append(f"❌ {name}: {str(e)[:120]}")
            continue
        cnt = 0
        for v in vids:
            sn = v["snippet"]
            if (secs(v["contentDetails"]["duration"]) <= 180 and not a.shorts) or sn["publishedAt"][:19] < since \
                    or v["id"] in done:
                continue
            meta = {"title": sn["title"], "description": sn.get("description", ""), "tags": sn.get("tags", [])}
            try:
                new = hashtags.yt_meta(meta, name)
                if new.get("description") == meta["description"] and new.get("tags") == meta["tags"]:
                    continue
                if a.dry_run:
                    print(f"--- {name}: {sn['title']}\nTAGS ({len(new['tags'])}): {', '.join(new['tags'])}\n"
                          f"BESCHREIBUNG:\n{new['description'][:700]}\n")
                else:
                    body = {"id": v["id"], "snippet": {"title": sn["title"], "description": new["description"][:4900],
                                                      "tags": new["tags"], "categoryId": sn["categoryId"]}}
                    for k in ("defaultLanguage", "defaultAudioLanguage"):
                        if sn.get(k):
                            body["snippet"][k] = sn[k]
                    yt.videos().update(part="snippet", body=body).execute()
                    done.add(v["id"])
                cnt += 1
                time.sleep(2)
            except Exception as e:  # noqa: BLE001
                report.append(f"❌ {name} · {sn['title'][:40]}: {str(e)[:150]}")
        n_ok += cnt
        report.append(f"✅ {name}: {cnt} Videos {'(Probe)' if a.dry_run else 'optimiert'}")
    if not a.dry_run:
        DONE.write_text(json.dumps(sorted(done), indent=0))
    print("\n".join(report))
    print(f"::notice title=SEO nachträglich ({n_ok})::{' ⏎ '.join(report)[:3800]}")


if __name__ == "__main__":
    main()
