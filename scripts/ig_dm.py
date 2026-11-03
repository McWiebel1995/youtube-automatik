#!/usr/bin/env python3
"""
Kommentar-Stichwort -> Direktnachricht (Instagram, offizielle "Private Reply"-Funktion).

  Beispiel facts_mcwiebel: Caption sagt "Comment QUIZ and I'll DM you 3 bonus questions".
  Wer QUIZ kommentiert, bekommt automatisch eine DM mit 3 Bonusfragen (+ Lösungen) und öffentlich ein kurzes "Sent! 📩".

  python scripts/ig_dm.py --probe     # darf der Zugang Nachrichten senden?
  python scripts/ig_dm.py             # neue Stichwort-Kommentare beantworten

Regeln von Instagram: nur 1 private Antwort pro Kommentar, nur innerhalb von 7 Tagen. Gemerkt in data/ig_dm/done.json.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT / "anime")]
import instagram  # noqa: E402

STATE = ROOT / "data" / "ig_dm" / "done.json"
CACHE = ROOT / "data" / "ig_dm" / "bonus.json"
CAMPAIGNS = {
    "whatif": {"keyword": "QUIZ", "public_reply": ["Sent! Check your DMs 📩", "Just sent it to your inbox 📩🧠",
                                                   "In your DMs now! 📩 Good luck!"],
               "channel_url": "https://www.youtube.com/@BeyondtheIf"},
}
BONUS_TASK = """Instagram post caption: "{caption}"
Write 3 NEW bonus quiz questions on exactly the same topic (factually 100% correct, short), each with 3 options A/B/C,
and the answers at the end. Friendly DM tone, English, max 600 characters total, a few emojis.
Format:
🧠 Bonus round!
1) question
A) … B) … C) …
2) …
3) …
Answers: 1-X, 2-X, 3-X
Answer ONLY JSON: {{"text": "..."}}"""


def load(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def save(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def private_reply(token, user_id, comment_id, text):
    r = requests.post(f"{instagram.API}/{user_id}/messages", timeout=60,
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                      json={"recipient": {"comment_id": comment_id}, "message": {"text": text}})
    js = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code >= 400 or "error" in js:
        e = js.get("error", {})
        raise instagram.IGError(f"{e.get('message', r.text[:200])} (Code {e.get('code')}/{e.get('error_subcode')})")
    return js


def bonus(media, cache):
    if media["id"] in cache:
        return cache[media["id"]]
    import gemini
    js = gemini.ask_json(BONUS_TASK.format(caption=(media.get("caption") or "")[:600]), temperature=0.5)
    cache[media["id"]] = js["text"].strip()[:900]
    return cache[media["id"]]


def run(key, probe, report):
    camp = CAMPAIGNS[key]
    tok = instagram.token_for(key)
    me = instagram.me(tok)
    uid, uname = me.get("user_id") or me.get("id"), me.get("username")
    if probe:
        try:
            instagram._req("GET", "me/conversations", tok, platform="instagram", limit=1)
            report.append(f"@{uname}: Nachrichten-Berechtigung ✅")
        except Exception as e:  # noqa: BLE001
            report.append(f"@{uname}: Nachrichten-Berechtigung ❌ ({str(e)[:160]})")
        return
    done, cache = set(load(STATE, [])), load(CACHE, {})
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=6, hours=20)
    media = instagram._req("GET", "me/media", tok, fields="id,caption,timestamp", limit=25).get("data", [])
    kw = re.compile(rf"\b{camp['keyword']}\b", re.I)
    n = 0
    for m in media:
        if dt.datetime.fromisoformat(m["timestamp"].replace("+0000", "+00:00")) < since:
            continue
        cs = instagram._req("GET", f"{m['id']}/comments", tok, fields="id,text,username,timestamp", limit=50).get("data", [])
        for c in cs:
            if c["id"] in done or c.get("username") == uname or not kw.search(c.get("text") or ""):
                continue
            try:
                text = bonus(m, cache) + f"\n\nNew quizzes every day on YouTube 👉 {camp['channel_url']}"
                private_reply(tok, uid, c["id"], text)
                try:
                    instagram._req("POST", f"{c['id']}/replies", tok,
                                   message=camp["public_reply"][len(done) % len(camp["public_reply"])])
                except Exception:  # noqa: BLE001
                    pass
                report.append(f"📩 @{c.get('username')} ({m['id']})")
                n += 1
            except Exception as e:  # noqa: BLE001
                report.append(f"❌ @{c.get('username')}: {str(e)[:160]}")
            done.add(c["id"])
    save(STATE, sorted(done)[-5000:])
    save(CACHE, dict(list(cache.items())[-200:]))
    report.append(f"@{uname}: {n} DMs gesendet")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    a = ap.parse_args()
    report = []
    for key in CAMPAIGNS:
        if key not in instagram.ACCOUNTS:
            report.append(f"{key}: kein Zugang")
            continue
        try:
            run(key, a.probe, report)
        except Exception as e:  # noqa: BLE001
            report.append(f"{key}: Fehler {str(e)[:200]}")
    print("\n".join(report))
    print(f"::notice title=Kommentar-DMs::{' ⏎ '.join(report)[:3800]}")


if __name__ == "__main__":
    main()
