#!/usr/bin/env python3
"""Prüft alle 6 YouTube-Tokens: gültig? richtiger Kanal? lange Videos erlaubt? (lädt nichts hoch)"""
import os
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import upload  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
chans = list(yaml.safe_load(open(ROOT / "config/channels.yaml"))["channels"].values()) + \
        list(yaml.safe_load(open(ROOT / "config/kids.yaml"))["channels"].values())
lines, bad = [], 0
for ch in chans:
    tok = os.environ.get(ch["token_secret"])
    try:
        if not tok:
            raise RuntimeError("Secret fehlt")
        yt = upload.service(tok)
        res = yt.channels().list(part="snippet,status", mine=True).execute()
        it = (res.get("items") or [{}])[0]
        title = it.get("snippet", {}).get("title", "?")
        long_ok = it.get("status", {}).get("longUploadsStatus", "?")
        norm = lambda s: "".join(c for c in s.lower() if c.isalnum())  # noqa: E731
        ok = norm(ch["name"]) in norm(title) or norm(title) in norm(ch["name"])
        bad += not ok
        lines.append(f"{'✅' if ok else '❌'} {ch['token_secret']}: Kanal »{title}« (erwartet »{ch['name']}«), "
                     f"lange Videos: {long_ok}")
    except Exception as e:  # noqa: BLE001
        bad += 1
        lines.append(f"❌ {ch['token_secret']}: {str(e)[:150]}")
msg = " | ".join(lines)
print("\n".join(lines))
print(f"::{'error' if bad else 'notice'} title=Tokencheck::{msg}")
