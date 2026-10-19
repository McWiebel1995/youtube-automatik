#!/usr/bin/env python3
"""
Holt ein YouTube-Refresh-Token per Geräte-Code (ideal fürs Handy) und speichert es
direkt als GitHub-Secret – das Token taucht nie im Log auf.

Läuft in GitHub Actions (Workflow "Token holen"). Benötigt:
  YT_CLIENT_ID / YT_CLIENT_SECRET  (OAuth-Client vom Typ "Fernseher und Geräte mit begrenzter Eingabe")
  GH_PAT                           (GitHub-Token mit Recht "Secrets: Read and write")
  SECRET_NAME                      (z. B. YT_REFRESH_TOKEN_REGEN)
"""
import os
import subprocess
import sys
import time

import requests

SCOPE = "https://www.googleapis.com/auth/youtube"


def main():
    cid, csec = os.environ.get("YT_CLIENT_ID"), os.environ.get("YT_CLIENT_SECRET")
    name = os.environ["SECRET_NAME"]
    label = os.environ.get("CHANNEL_LABEL", name)
    if not cid or not csec:
        sys.exit("❌ Secrets YT_CLIENT_ID / YT_CLIENT_SECRET fehlen.")
    if not os.environ.get("GH_TOKEN"):
        sys.exit("❌ Secret GH_PAT fehlt (wird zum Speichern des Tokens gebraucht).")

    r = requests.post("https://oauth2.googleapis.com/device/code",
                      data={"client_id": cid, "scope": SCOPE}, timeout=30)
    if r.status_code != 200:
        sys.exit(f"❌ Google lehnt ab: {r.text}\n"
                 "Ist der OAuth-Client vom Typ 'Fernseher und Geräte mit begrenzter Eingabe'?")
    d = r.json()
    bar = "=" * 52
    print(f"\n{bar}\n"
          f"  KANAL:  {label}\n\n"
          f"  1. Öffne auf dem Handy:   {d['verification_url']}\n"
          f"  2. Gib diesen Code ein:   {d['user_code']}\n"
          f"  3. Mit Google anmelden und den Kanal\n"
          f"     »{label}« auswählen, dann 'Zulassen'.\n\n"
          f"  Der Code ist {d['expires_in'] // 60} Minuten gültig.\n{bar}\n", flush=True)

    interval, deadline = d.get("interval", 5), time.time() + d["expires_in"]
    while time.time() < deadline:
        time.sleep(interval)
        t = requests.post("https://oauth2.googleapis.com/token", timeout=30, data={
            "client_id": cid, "client_secret": csec, "device_code": d["device_code"],
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}).json()
        err = t.get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        if err:
            sys.exit(f"❌ Abgebrochen: {err} – {t.get('error_description', '')}")
        refresh = t.get("refresh_token")
        if not refresh:
            sys.exit("❌ Kein Refresh-Token erhalten. Bitte in myaccount.google.com/permissions "
                     "den Zugriff der App entfernen und erneut versuchen.")
        # Kanal prüfen, damit klar ist, welcher Kanal verbunden wurde
        me = requests.get("https://www.googleapis.com/youtube/v3/channels",
                          params={"part": "snippet", "mine": "true"},
                          headers={"Authorization": f"Bearer {t['access_token']}"}, timeout=30).json()
        title = (me.get("items") or [{}])[0].get("snippet", {}).get("title", "?")
        subprocess.run(["gh", "secret", "set", name, "--body", refresh,
                        "--repo", os.environ["GITHUB_REPOSITORY"]], check=True)
        print(f"\n✅ Verbunden mit Kanal: »{title}«\n✅ Gespeichert als Secret {name}\n")
        if label.lower().replace(" ", "") not in title.lower().replace(" ", ""):
            print(f"⚠ Achtung: erwartet war »{label}«. Falls falsch, einfach nochmal ausführen "
                  "und den richtigen Kanal wählen.")
        return
    sys.exit("❌ Zeit abgelaufen – Workflow einfach nochmal starten.")


if __name__ == "__main__":
    main()
