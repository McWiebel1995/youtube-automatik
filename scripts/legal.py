#!/usr/bin/env python3
"""
Impressum & Datenschutz: Pflichtangaben für geschäftsmäßige Kanäle (Abmahnschutz).

  footer(lang)                      -> Zeile für jede Videobeschreibung
  python scripts/legal.py           -> alle Kanalbeschreibungen + alle Videos ergänzen (fehlende Zeile anfügen)
  python scripts/legal.py --dry-run
"""
import argparse
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "anime")]

IMPRESSUM = "https://cicco-fam.de/impressum"
DATENSCHUTZ = "https://cicco-fam.de/datenschutz"
MARK = "cicco-fam.de/impressum"
GERMAN = ("Mondmelodie", "Gute-Nacht-Kiste", "Ruhige Gedanken")


def footer(channel_name=""):
    if any(g.lower() in (channel_name or "").lower() for g in GERMAN):
        return f"Impressum: {IMPRESSUM} · Datenschutz: {DATENSCHUTZ}"
    return f"Legal notice (Impressum): {IMPRESSUM} · Privacy: {DATENSCHUTZ}"


def add(text, channel_name=""):
    text = text or ""
    if MARK in text:
        return text
    return f"{text.rstrip()}\n\n{footer(channel_name)}".strip()[:4990]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    import analytics_report
    import upload
    report = []
    for key, name, secret in analytics_report.yt_channels():
        if not os.environ.get(secret):
            continue
        try:
            yt = upload.service(os.environ[secret])
            ch = yt.channels().list(part="brandingSettings,contentDetails", mine=True).execute()["items"][0]
            bs = ch.get("brandingSettings", {})
            desc = bs.get("channel", {}).get("description", "")
            ch_done = MARK in desc
            if not ch_done and not a.dry_run:
                bs.setdefault("channel", {})["description"] = add(desc, name)[:1000]
                yt.channels().update(part="brandingSettings", body={"id": ch["id"], "brandingSettings": bs}).execute()
            pl = ch["contentDetails"]["relatedPlaylists"]["uploads"]
            ids, tok = [], None
            while True:
                r = yt.playlistItems().list(part="contentDetails", playlistId=pl, maxResults=50, pageToken=tok).execute()
                ids += [i["contentDetails"]["videoId"] for i in r.get("items", [])]
                tok = r.get("nextPageToken")
                if not tok or len(ids) >= 500:
                    break
            n = 0
            for k in range(0, len(ids), 50):
                for v in yt.videos().list(part="snippet", id=",".join(ids[k:k + 50])).execute().get("items", []):
                    sn = v["snippet"]
                    if MARK in sn.get("description", ""):
                        continue
                    n += 1
                    if a.dry_run:
                        continue
                    body = {"id": v["id"], "snippet": {"title": sn["title"], "categoryId": sn["categoryId"],
                                                      "description": add(sn.get("description", ""), name),
                                                      "tags": sn.get("tags", [])}}
                    for f in ("defaultLanguage", "defaultAudioLanguage"):
                        if sn.get(f):
                            body["snippet"][f] = sn[f]
                    yt.videos().update(part="snippet", body=body).execute()
                    time.sleep(0.5)
            report.append(f"✅ {name}: Kanal {'hatte es schon' if ch_done else 'ergänzt'}, {n} Videos "
                          f"{'würden ergänzt' if a.dry_run else 'ergänzt'}")
        except Exception as e:  # noqa: BLE001
            report.append(f"❌ {name}: {str(e)[:200]}")
    print("\n".join(report))
    print(f"::notice title=Impressum::{' ⏎ '.join(report)[:3800]}")


if __name__ == "__main__":
    main()
