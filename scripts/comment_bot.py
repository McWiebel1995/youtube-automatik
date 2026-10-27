#!/usr/bin/env python3
"""
Kommentar-Bot für YouTube und Instagram: liest neue Kommentare, Gemini schreibt eine passende Antwort im Ton des
Kanals, der Bot antwortet. Spam/Beleidigungen/heikle Fälle werden NICHT beantwortet, sondern im Bericht gelistet.

  python scripts/comment_bot.py --probe        # nur prüfen: Zugänge & Berechtigungen
  python scripts/comment_bot.py --dry-run      # Vorschläge anzeigen, nichts posten
  python scripts/comment_bot.py                # wirklich antworten

Merkt sich beantwortete Kommentare in data/comment_bot/replied.json (keine Doppel-Antworten).
"""
import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT / "anime")]

STATE = ROOT / "data" / "comment_bot" / "replied.json"
LOG = ROOT / "data" / "comment_bot" / "log.jsonl"
MAX_AGE_DAYS = 14
MAX_PER_CHANNEL = 15

PERSONAS = {
    "calm": "Calm Haven – relaxing rain/fire/water sounds for sleep and focus. Tone: calm, warm, gentle, short. "
            "Example: 'So glad it helped you drift off 🌧️'.",
    "whatif": "Beyond the If – science what-if videos, news shorts and quizzes. Tone: curious, friendly, enthusiastic "
              "about science. If someone asks a factual question, answer in one careful sentence only if you are sure; "
              "otherwise say it's a great question. If someone corrects a fact, thank them and don't argue.",
    "astro": "dear.zodiac – poetic daily notes for each zodiac sign (entertainment). Tone: warm, cosmic, a little "
             "mystical, inclusive. Never predict health, money or real-life decisions.",
    "mondmelodie": "Mondmelodie – Spieluhr-Einschlafmusik für Babys. Ton: herzlich, ruhig, an Eltern gerichtet, Du-Form, "
                   "Deutsch. Keine medizinischen Ratschläge zu Babyschlaf – bei Sorgen auf Kinderarzt/Hebamme verweisen.",
    "gutenacht": "Gute-Nacht-Kiste – Gute-Nacht-Geschichten für Kinder (2–6). Ton: herzlich, an Eltern gerichtet, Du-Form, "
                 "Deutsch. Keine Erziehungs- oder Medizinratschläge.",
}
RULES = """Rules for every reply:
- Reply in the commenter's language. Max 2 short sentences, natural, human-sounding, 0–2 fitting emojis. No hashtags, no links.
- Be specific to what they wrote (and to the video/post), never generic copy-paste.
- If they ask whether a person or a bot answers: be honest (replies are written with AI help and read by the creator).
- Never promise anything (collaborations, giveaways, personal contact) – for business requests: action "flag".
- Medical, legal, financial questions: no advice, kindly point to a professional.
- Kids' channels: if the commenter is clearly a child, reply very short and neutral, no follow-up question.
- action "skip" for: spam, self-promotion, links, bots, hate, insults, sexual content, gibberish, comments that need no answer.
- action "flag" for: complaints with details, copyright claims, business inquiries, anything sensitive the creator should see.
- Otherwise action "reply". Pure praise ("love this") deserves a short warm thank-you, ideally with a gentle question."""
TASK = """You manage comments for this channel: {persona}
{rules}
Comments (JSON): {items}
Answer ONLY JSON: {{"replies":[{{"id":"...","action":"reply|skip|flag","reply":"...","reason":"max 6 words"}}]}}"""


def load_state():
    try:
        return set(json.loads(STATE.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        return set()


def save_state(ids):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(sorted(ids)[-20000:], indent=0), encoding="utf-8")


def log(entry):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def recent(ts):
    try:
        t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00").replace("+0000", "+00:00"))
        return (dt.datetime.now(dt.timezone.utc) - t).days <= MAX_AGE_DAYS
    except Exception:  # noqa: BLE001
        return True


def decide(persona, items):
    """Gemini entscheidet pro Kommentar: reply/skip/flag + Antworttext."""
    import gemini
    if not items:
        return {}
    out = {}
    for k in range(0, len(items), 20):
        js = gemini.ask_json(TASK.format(persona=PERSONAS[persona], rules=RULES,
                                         items=json.dumps(items[k:k + 20], ensure_ascii=False)), temperature=0.7)
        for r in js.get("replies", []):
            out[str(r.get("id"))] = r
    return out


# ----------------------------------------------------------------- YouTube
def yt_channels():
    relax = yaml.safe_load(open(ROOT / "config/channels.yaml"))["channels"]
    wi = yaml.safe_load(open(ROOT / "config/whatif.yaml"))["channel"]
    out = [(c["name"], c["token_secret"], "calm") for c in relax.values()]
    out += [(wi["name"], wi["token_secret"], "whatif"), ("dear.zodiac", "YT_REFRESH_TOKEN_LERNEN", "astro")]
    return out   # Mondmelodie & Gute-Nacht-Kiste: "für Kinder" -> YouTube erlaubt dort keine Kommentare


def yt_scopes(yt_creds_token):
    import requests
    r = requests.get("https://oauth2.googleapis.com/tokeninfo", params={"access_token": yt_creds_token}, timeout=30)
    return r.json().get("scope", "")


def yt_run(name, secret, persona, replied, dry, probe, report):
    import upload
    tok = os.environ.get(secret)
    if not tok:
        report.append(f"YT {name}: kein Zugang ({secret} fehlt)")
        return
    yt = upload.service(tok)
    me = yt.channels().list(part="id,snippet", mine=True).execute()["items"][0]
    cid = me["id"]
    creds = yt._http.credentials
    scopes = yt_scopes(creds.token)
    can_reply = "youtube.force-ssl" in scopes
    res = yt.commentThreads().list(part="snippet,replies", allThreadsRelatedToChannelId=cid, maxResults=50,
                                   order="time", textFormat="plainText").execute()
    threads = res.get("items", [])
    items, meta = [], {}
    vids = set()
    for th in threads:
        top = th["snippet"]["topLevelComment"]
        sn = top["snippet"]
        if th["id"] in replied or sn.get("authorChannelId", {}).get("value") == cid or not recent(sn["publishedAt"]):
            continue
        rep = (th.get("replies") or {}).get("comments", [])
        if any(r["snippet"].get("authorChannelId", {}).get("value") == cid for r in rep):
            replied.add(th["id"])
            continue
        vids.add(sn.get("videoId"))
        meta[th["id"]] = sn
        items.append({"id": th["id"], "author": sn.get("authorDisplayName", ""), "text": sn.get("textDisplay", "")[:600],
                      "video": sn.get("videoId")})
    titles = {}
    if vids - {None}:
        for v in yt.videos().list(part="snippet", id=",".join(list(vids - {None})[:50])).execute().get("items", []):
            titles[v["id"]] = v["snippet"]["title"]
    for it in items:
        it["video"] = titles.get(it["video"], "")
    if probe:
        report.append(f"YT {name}: {len(threads)} Kommentar-Threads, {len(items)} neu offen · "
                      f"Antworten erlaubt: {'✅' if can_reply else '❌ (Berechtigung youtube.force-ssl fehlt)'}")
        return
    items = items[:MAX_PER_CHANNEL]
    dec = decide(persona, items)
    for it in items:
        d = dec.get(it["id"], {"action": "skip", "reason": "keine Entscheidung"})
        line = f"YT {name} · „{it['text'][:80]}“ → {d['action']}: {d.get('reply') or d.get('reason', '')}"
        if d["action"] == "reply" and d.get("reply") and not dry:
            if not can_reply:
                report.append(line + "  (nicht gesendet: Berechtigung fehlt)")
                continue
            yt.comments().insert(part="snippet", body={"snippet": {"parentId": it["id"],
                                                                   "textOriginal": d["reply"][:500]}}).execute()
        if not dry:
            replied.add(it["id"])
            log({"t": dt.datetime.now().isoformat(timespec="seconds"), "pf": "yt", "ch": name, "id": it["id"],
                 "comment": it["text"], **d})
        report.append(line)


# ----------------------------------------------------------------- Instagram
IG_PERSONA = {"calmhaven": "calm", "mondmelodie": "mondmelodie", "gutenacht": "gutenacht", "astro": "astro",
              "whatif": "whatif"}


def ig_run(key, replied, dry, probe, report):
    import instagram
    try:
        tok = instagram.token_for(key)
    except Exception as e:  # noqa: BLE001
        report.append(f"IG {key}: kein Zugang ({e})")
        return
    me = instagram.me(tok)
    uname = me.get("username", key)
    media = instagram._req("GET", "me/media", tok, fields="id,caption,timestamp,comments_count", limit=20).get("data", [])
    items = []
    for m in media:
        if not m.get("comments_count") or not recent(m.get("timestamp", "")):
            continue
        cs = instagram._req("GET", f"{m['id']}/comments", tok,
                            fields="id,text,username,timestamp,replies{username}", limit=50).get("data", [])
        for c in cs:
            if c["id"] in replied or c.get("username") == uname:
                continue
            if any(r.get("username") == uname for r in (c.get("replies") or {}).get("data", [])):
                replied.add(c["id"])
                continue
            items.append({"id": c["id"], "author": c.get("username", ""), "text": (c.get("text") or "")[:600],
                          "post": (m.get("caption") or "").split("\n")[0][:120]})
    if probe:
        report.append(f"IG @{uname}: {len(media)} Beiträge, {len(items)} offene Kommentare (Lesen ✅)")
        return
    items = items[:MAX_PER_CHANNEL]
    dec = decide(IG_PERSONA.get(key, "calm"), items)
    for it in items:
        d = dec.get(it["id"], {"action": "skip", "reason": "keine Entscheidung"})
        line = f"IG @{uname} · „{it['text'][:80]}“ → {d['action']}: {d.get('reply') or d.get('reason', '')}"
        if d["action"] == "reply" and d.get("reply") and not dry:
            try:
                instagram._req("POST", f"{it['id']}/replies", tok, message=d["reply"][:500])
            except Exception as e:  # noqa: BLE001
                report.append(line + f"  (nicht gesendet: {str(e)[:120]})")
                continue
        if not dry:
            replied.add(it["id"])
            log({"t": dt.datetime.now().isoformat(timespec="seconds"), "pf": "ig", "ch": uname, "id": it["id"],
                 "comment": it["text"], **d})
        report.append(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--probe", action="store_true")
    a = ap.parse_args()
    replied = load_state()
    report = []
    for name, secret, persona in yt_channels():
        try:
            yt_run(name, secret, persona, replied, a.dry_run, a.probe, report)
        except Exception as e:  # noqa: BLE001
            report.append(f"YT {name}: Fehler {str(e)[:200]}")
    import instagram
    for key in list(instagram.ACCOUNTS):
        try:
            ig_run(key, replied, a.dry_run, a.probe, report)
        except Exception as e:  # noqa: BLE001
            report.append(f"IG {key}: Fehler {str(e)[:200]}")
    if not a.dry_run and not a.probe:
        save_state(replied)
    print("\n".join(report))
    text = " ⏎ ".join(report) or "keine neuen Kommentare"
    for k in range(0, len(text), 3800):
        print(f"::notice title=Kommentare {k // 3800 + 1}::{text[k:k + 3800]}")
    out = Path(os.environ.get("GITHUB_STEP_SUMMARY", "/dev/null"))
    try:
        with out.open("a", encoding="utf-8") as f:
            f.write("## Kommentar-Bot\n\n" + "\n".join(f"- {r}" for r in report) + "\n")
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    main()
