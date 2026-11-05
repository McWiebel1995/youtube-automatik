#!/usr/bin/env python3
"""
Themenwünsche der Zuschauer (Beyond the If): liest neue Kommentare auf YouTube + Instagram, erkennt Wünsche wie
"do one about sharks!" / "next quiz: Egypt" und sammelt sie in data/topic_requests.json (mit Stimmen & Namen).
Das Quiz nimmt regelmäßig den meistgewünschten Wunsch und sagt im Video "You asked for it!".
"""
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT / "anime")]
FILE = ROOT / "data" / "topic_requests.json"
SEEN = ROOT / "data" / "topic_requests_seen.json"
TASK = """These are viewer comments on a science quiz / what-if channel. Find comments that REQUEST a topic for a future
quiz or video (e.g. "do one about sharks", "next: ancient Egypt", "quiz on volcanoes please", "can you do the moon?").
Ignore everything else (praise, scores like 3/3, questions about the video). Topic must be a family-friendly
science/nature/history/space topic in 1–4 English words. No people's names, no politics, no violence.
Comments (JSON): {items}
Answer ONLY JSON: {{"requests": [{{"id": "...", "topic": "..."}}]}}"""


def _load(p, d):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return d


def norm(t):
    return re.sub(r"[^a-z0-9 ]", "", (t or "").lower()).strip()


def collect():
    reqs, seen = _load(FILE, {}), set(_load(SEEN, []))
    items = []
    try:                                              # YouTube (1–2 Einheiten Kontingent)
        import upload
        yt = upload.service(os.environ["YT_REFRESH_TOKEN_WHATIF"])
        cid = yt.channels().list(part="id", mine=True).execute()["items"][0]["id"]
        for th in yt.commentThreads().list(part="snippet", allThreadsRelatedToChannelId=cid, maxResults=100,
                                           order="time", textFormat="plainText").execute().get("items", []):
            sn = th["snippet"]["topLevelComment"]["snippet"]
            if th["id"] not in seen and sn.get("authorChannelId", {}).get("value") != cid:
                items.append({"id": "yt:" + th["id"], "user": sn.get("authorDisplayName", ""), "text": sn.get("textDisplay", "")[:300]})
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ Themenwünsche YouTube: {str(e)[:120]}")
    try:                                              # Instagram facts_mcwiebel
        import instagram
        if "whatif" in instagram.ACCOUNTS:
            tok = instagram.token_for("whatif")
            me = instagram.me(tok).get("username")
            for m in instagram._req("GET", "me/media", tok, fields="id", limit=15).get("data", []):
                for c in instagram._req("GET", f"{m['id']}/comments", tok, fields="id,text,username", limit=50).get("data", []):
                    if "ig:" + c["id"] not in seen and c.get("username") != me:
                        items.append({"id": "ig:" + c["id"], "user": "@" + c.get("username", ""), "text": (c.get("text") or "")[:300]})
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ Themenwünsche Instagram: {str(e)[:120]}")
    if items:
        import gemini
        by_id = {x["id"]: x for x in items}
        for k in range(0, len(items), 40):
            try:
                js = gemini.ask_json(TASK.format(items=json.dumps([{"id": x["id"], "text": x["text"]} for x in items[k:k + 40]],
                                                                  ensure_ascii=False)), temperature=0.2)
            except Exception as e:  # noqa: BLE001
                print(f"  ⚠ Themenwünsche erkennen: {str(e)[:120]}")
                continue
            for r in (js.get("requests", []) if isinstance(js, dict) else js):
                src = by_id.get(str(r.get("id")))
                t = norm(r.get("topic"))
                if not src or not t or len(t) > 40:
                    continue
                e = reqs.setdefault(t, {"topic": r["topic"].strip(), "users": [], "count": 0, "used": False,
                                        "first": dt.date.today().isoformat()})
                if src["user"] not in e["users"]:
                    e["users"].append(src["user"])
                    e["count"] += 1
        seen |= set(by_id)
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(reqs, ensure_ascii=False, indent=1), encoding="utf-8")
    SEEN.write_text(json.dumps(sorted(seen)[-5000:]), encoding="utf-8")
    return reqs


def top_open(reqs):
    open_ = [e for e in reqs.values() if not e.get("used")]
    return max(open_, key=lambda e: (e["count"], e["first"] < "9"), default=None)


def mark_used(topic):
    reqs = _load(FILE, {})
    if norm(topic) in reqs:
        reqs[norm(topic)]["used"] = True
        reqs[norm(topic)]["used_on"] = dt.date.today().isoformat()
        FILE.write_text(json.dumps(reqs, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    r = collect()
    print(json.dumps(r, ensure_ascii=False, indent=1))
