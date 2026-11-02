#!/usr/bin/env python3
"""
Impressum & Datenschutz: Pflichtangaben für geschäftsmäßige Kanäle (Abmahnschutz).

  footer(lang)                      -> Zeile für jede Videobeschreibung
  python scripts/legal.py           -> alle Kanalbeschreibungen + alle Videos ergänzen (fehlende Zeile anfügen)
  python scripts/legal.py --dry-run
"""
import argparse
import os
import re
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


def strip(text):
    """Impressum-Zeile wieder entfernen."""
    lines = [ln for ln in (text or "").split("\n") if MARK not in ln]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--remove", action="store_true", help="Impressum-Zeile überall wieder entfernen")
    ap.add_argument("--max", type=int, default=50, help="max. Video-Änderungen pro Lauf (je 50 Kontingent-Einheiten)")
    a = ap.parse_args()
    budget = [a.max]
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
            ch_done = (MARK not in desc) if a.remove else (MARK in desc)
            if not ch_done and not a.dry_run:
                bs.setdefault("channel", {})["description"] = (strip(desc) if a.remove else add(desc, name))[:1000]
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
                    has = MARK in sn.get("description", "")
                    if has != a.remove:
                        continue
                    if budget[0] <= 0:
                        break
                    n += 1
                    budget[0] -= 1
                    if a.dry_run:
                        continue
                    body = {"id": v["id"], "snippet": {"title": sn["title"], "categoryId": sn["categoryId"],
                                                      "description": strip(sn.get("description", "")) if a.remove
                                                      else add(sn.get("description", ""), name),
                                                      "tags": sn.get("tags", [])}}
                    for f in ("defaultLanguage", "defaultAudioLanguage"):
                        if sn.get(f):
                            body["snippet"][f] = sn[f]
                    yt.videos().update(part="snippet", body=body).execute()
                    time.sleep(0.5)
            verb = "entfernt" if a.remove else "ergänzt"
            report.append(f"✅ {name}: Kanal {'schon erledigt' if ch_done else verb}, {n} Videos "
                          f"{'würden ' + verb if a.dry_run else verb}")
        except Exception as e:  # noqa: BLE001
            report.append(f"❌ {name}: {str(e)[:200]}")
    print("\n".join(report))
    print(f"::notice title=Impressum::{' ⏎ '.join(report)[:3800]}")


if __name__ == "__main__":
    main()
