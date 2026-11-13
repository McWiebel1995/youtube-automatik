#!/usr/bin/env python3
"""
Konten-Ampel für die Cicco Zentrale -> site/accounts.json (+ Clip-Lab- und Kosten-Daten nach site/).

Nur lesend. Enthält NIE Tokens oder Passwörter – nur: verbunden ja/nein, Kontoname, Hinweis.
"""
import json
import os
import shutil
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
SITE = ROOT / "site"


def yt_list():
    relax = yaml.safe_load(open(ROOT / "config/channels.yaml"))["channels"]
    kids = yaml.safe_load(open(ROOT / "config/kids.yaml"))["channels"]
    wi = yaml.safe_load(open(ROOT / "config/whatif.yaml"))["channel"]
    out = [(c["name"], c["token_secret"], "Medienhaus") for c in relax.values()]
    out += [(c["name"], c["token_secret"], "Medienhaus") for c in kids.values()]
    out += [(wi["name"], wi["token_secret"], "Medienhaus"), ("Ruhige Gedanken", "YT_REFRESH_TOKEN_GEDANKEN", "Medienhaus"),
            ("The Clip Lab", "YT_REFRESH_TOKEN_CLIPLAB", "Clip Lab")]
    return out


def main():
    acc = []
    import upload
    for name, secret, proj in yt_list():
        row = {"platform": "YouTube", "name": name, "project": proj, "via": "Schnittstelle"}
        tok = os.environ.get(secret)
        if not tok:
            row.update(state="off", note="nicht verbunden")
        else:
            try:
                it = upload.service(tok).channels().list(part="snippet", mine=True).execute()["items"][0]
                row.update(state="ok", account=it["snippet"]["title"])
            except Exception as e:  # noqa: BLE001
                row.update(state="err", note=("Kontingent aufgebraucht" if "quota" in str(e).lower()
                                              else "Zugang abgelaufen – neu verbinden")[:120])
        acc.append(row)
    try:
        import instagram
        for key, (secret, user) in instagram.ACCOUNTS.items():
            row = {"platform": "Instagram", "name": "@" + str(user or key), "project": "Clip Lab" if key == "cliplab"
                   else "Medienhaus", "via": "Schnittstelle"}
            try:
                me = instagram.me(instagram.token_for(key))
                row.update(state="ok", account="@" + me.get("username", ""))
            except Exception:  # noqa: BLE001
                row.update(state="err", note="Zugang prüfen")
            acc.append(row)
    except Exception as e:  # noqa: BLE001
        acc.append({"platform": "Instagram", "name": "alle", "state": "err", "note": str(e)[:120]})
    for platform, name, proj, note in (
            ("TikTok", "@thecliplab474", "Clip Lab", "über dein Chrome – PC muss an sein"),
            ("Outlook", "Clip-Lab-Postfach", "Clip Lab", "über dein Chrome – PC muss an sein"),
            ("Whop / Content Rewards", "thecliplab", "Clip Lab", "über dein Chrome – PC muss an sein")):
        acc.append({"platform": platform, "name": name, "project": proj, "via": "Chrome", "state": "chrome", "note": note})
    for name, repo, proj in (("tacticn.de", "tactical-symbol-hub", "Tacticn Shop"),
                             ("cicco-fam.de", "ciccone-kitchen-stories", "CICCO Feinkost")):
        acc.append({"platform": "Webseiten (Lovable)", "name": name, "account": f"{name} · GitHub {repo}", "project": proj,
                    "via": "GitHub-Sync", "state": "ok", "note": "Änderungen am Code gehen automatisch live"})
    for platform, env, note in (("Gemini (KI)", "GEMINI_API_KEY", "Texte, Auswahl"),
                                ("Modal (GPU)", "MODAL_TOKEN_ID", "Bilder, Stimmen")):
        acc.append({"platform": platform, "name": note, "project": "Maschinenraum", "via": "Schnittstelle",
                    "state": "ok" if os.environ.get(env) else "unknown"})
    SITE.mkdir(exist_ok=True)
    import datetime as dt
    (SITE / "accounts.json").write_text(json.dumps({"generated": dt.datetime.now(dt.timezone.utc).isoformat(
        timespec="seconds"), "accounts": acc}, ensure_ascii=False, indent=1), encoding="utf-8")
    for src, dst in ((ROOT / "data/cliplab/pending.json", "cliplab.json"), (ROOT / "data/modal_usage.json", "modal.json")):
        if src.exists():
            shutil.copy(src, SITE / dst)
    print(f"{len(acc)} Konten, {sum(a['state'] == 'ok' for a in acc)} ok")


if __name__ == "__main__":
    main()
