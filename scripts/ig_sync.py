#!/usr/bin/env python3
"""
Abgleich YouTube-Shorts <-> Instagram-Reels für alle Kanäle: Shorts, die es auf YouTube gibt, aber (noch) nicht auf
Instagram, werden nach und nach nachgeholt – ein paar pro Tag, nie alles auf einmal.

  python scripts/ig_sync.py --list          # Abgleich anzeigen (nichts posten)
  python scripts/ig_sync.py --post          # pro Instagram-Konto das Tageskontingent nachholen

Erkennung "schon auf Instagram": gleicher Titel in der Caption, sonst ein Reel desselben Kontos am selben Tag
(±1 Tag; bei Calm Haven zusätzlich passend Regen/Feuer/Wasser). Gemerkt in data/ig_sync/state.json.
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
STATE = ROOT / "data" / "ig_sync" / "state.json"
WINDOW_DAYS = 30                               # nur Shorts der letzten 30 Tage nachholen
PER_DAY = {"calmhaven": 2}                     # Nachhol-Kontingent pro Lauf (Standard 1)
SINCE = {"whatif": "2026-10-01"}               # ältere Inhalte (früheres Kanal-Thema) nicht übernehmen
CALM_WORDS = {"regen": r"rain|storm|thunder|drizzle", "kamin": r"fire|hearth|campfire|crackl|ember",
              "wasserfall": r"water|river|stream|ocean|wave|creek|brook|lake|sea"}


def channels():
    relax = yaml.safe_load(open(ROOT / "config/channels.yaml"))["channels"]
    kids = yaml.safe_load(open(ROOT / "config/kids.yaml"))["channels"]
    wi = yaml.safe_load(open(ROOT / "config/whatif.yaml"))["channel"]
    out = [(k, c["name"], c["token_secret"], "calmhaven") for k, c in relax.items()]
    ig = {"schlaf": "mondmelodie", "geschichten": "gutenacht", "lernen": "astro"}
    out += [(k, c["name"], c["token_secret"], ig[k]) for k, c in kids.items() if k in ig]
    out.append(("whatif", wi["name"], wi["token_secret"], "whatif"))
    return out


def load():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save(st):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def norm(s):
    s = re.sub(r"#\w+", " ", s or "").lower()
    return re.sub(r"[^a-z0-9äöüß]+", " ", s).strip()


def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00").replace("+0000", "+00:00"))


def secs(iso):
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    return 0 if not m else int(m[1] or 0) * 3600 + int(m[2] or 0) * 60 + int(m[3] or 0)


def yt_shorts(secret, since):
    import upload
    yt = upload.service(os.environ[secret])
    ch = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
    pl = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, tok = [], None
    while True:
        r = yt.playlistItems().list(part="contentDetails", playlistId=pl, maxResults=50, pageToken=tok).execute()
        new = [(i["contentDetails"]["videoId"], i["contentDetails"].get("videoPublishedAt", "")) for i in r.get("items", [])]
        ids += [v for v, d in new]
        tok = r.get("nextPageToken")
        if not tok or (new and new[-1][1] and new[-1][1] < since) or len(ids) >= 250:
            break
    out = []
    for k in range(0, len(ids), 50):
        for v in yt.videos().list(part="snippet,contentDetails,status", id=",".join(ids[k:k + 50])).execute()["items"]:
            pub = v["status"].get("publishAt") or v["snippet"]["publishedAt"]
            if v["status"].get("privacyStatus") != "public" or secs(v["contentDetails"]["duration"]) > 180 or pub < since:
                continue
            out.append({"id": v["id"], "title": v["snippet"]["title"], "desc": v["snippet"].get("description", ""),
                        "date": v["snippet"]["publishedAt"]})
    return out


def ig_reels(account):
    import instagram
    tok = instagram.token_for(account)
    out, after = [], None
    for _ in range(3):
        kw = {"fields": "id,caption,timestamp,media_type,media_product_type,permalink", "limit": 50}
        if after:
            kw["after"] = after
        js = instagram._req("GET", "me/media", tok, **kw)
        out += [m for m in js.get("data", []) if m.get("media_type") == "VIDEO"]
        after = (js.get("paging") or {}).get("cursors", {}).get("after")
        if not after or not js.get("data"):
            break
    return out


def compare(st):
    """-> {ig_account: [fehlende Shorts, neueste zuerst]}, Berichtzeilen"""
    now = dt.datetime.now(dt.timezone.utc)
    window = (now - dt.timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    by_acc, missing, lines = {}, {}, []
    for key, name, secret, acc in channels():
        by_acc.setdefault(acc, []).append((key, name, secret))
    for acc, chans in by_acc.items():
        try:
            reels = ig_reels(acc)
        except Exception as e:  # noqa: BLE001
            lines.append(f"IG {acc}: nicht erreichbar ({str(e)[:100]})")
            continue
        used = set()
        caps = {m["id"]: norm(m.get("caption")) for m in reels}
        miss = []
        for key, name, secret in chans:
            if not os.environ.get(secret):
                continue
            try:
                shorts = yt_shorts(secret, max(window, SINCE.get(acc, "")))
            except Exception as e:  # noqa: BLE001
                lines.append(f"YT {name}: Fehler {str(e)[:100]}")
                continue
            have = 0
            for v in sorted(shorts, key=lambda v: v["date"]):
                s = st.get(v["id"], {})
                if s.get("status") in ("posted", "failed", "matched"):
                    have += s.get("status") != "failed"
                    continue
                t = norm(v["title"])[:45]
                hit = next((mid for mid, c in caps.items() if mid not in used and len(t) > 12 and t in c), None)
                if not hit:                               # gleicher Tag, gleiches Konto (bei Calm Haven: passendes Thema)
                    cand = [m for m in reels if m["id"] not in used
                            and abs((ts(m["timestamp"]) - ts(v["date"])).total_seconds()) < 36 * 3600
                            and (acc != "calmhaven" or re.search(CALM_WORDS[key], (m.get("caption") or "").lower()))]
                    if cand:
                        hit = min(cand, key=lambda m: abs((ts(m["timestamp"]) - ts(v["date"])).total_seconds()))["id"]
                if hit:
                    used.add(hit)
                    st[v["id"]] = {"status": "matched", "ig": hit}
                    have += 1
                elif (now - ts(v["date"])).total_seconds() > 20 * 3600:   # ganz neue kommen über den normalen Weg
                    miss.append({**v, "channel": name, "key": key})
            lines.append(f"{name} → IG {acc}: {len(shorts)} Shorts (30 Tage), {have} schon auf Instagram, "
                         f"{len([m for m in miss if m['key'] == key])} fehlen")
        missing[acc] = sorted(miss, key=lambda v: v["date"], reverse=True)
    return missing, lines


def download(vid, work: Path):
    work.mkdir(parents=True, exist_ok=True)
    out = work / f"{vid}.mp4"
    r = subprocess.run(["yt-dlp", "-q", "--no-warnings", "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
                        "--merge-output-format", "mp4", "-o", str(out), f"https://www.youtube.com/shorts/{vid}"],
                       capture_output=True, text=True)
    if r.returncode or not out.exists():
        raise RuntimeError("Download: " + (r.stderr or r.stdout)[-250:])
    return out


def post_one(acc, v):
    import hashtags
    import ig_queue
    import instagram
    mp4 = download(v["id"], ROOT / "output" / "ig_sync")
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    url = ig_queue.upload_public(mp4, f"{acc}-sync-{stamp}.mp4")
    cover = ig_queue.make_cover(mp4)
    cover_url = ig_queue.upload_public(cover, f"{acc}-sync-{stamp}-cover.jpg") if cover else None
    title = re.sub(r"#\w+", "", v["title"]).strip()
    body = "\n".join(ln for ln in v["desc"].splitlines()
                     if not re.search(r"subscribe|abonnier|youtube\.com|youtu\.be|http", ln, re.I)).strip()
    body = re.sub(r"(\s*#\w+)+\s*$", "", body).strip()
    caption = hashtags.ig_caption(f"{title}\n\n{body}".strip()[:2000], acc)
    return instagram.publish_reel(acc, url, caption, cover_url=cover_url)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--post", action="store_true")
    a = ap.parse_args()
    st = load()
    missing, lines = compare(st)
    for acc, items in missing.items():
        lines += [f"  fehlt @{acc}: {v['date'][:10]} {v['channel']} · {v['title'][:60]}" for v in items[:6]]
    report = []
    if a.post:
        for acc, items in missing.items():
            for v in items[:PER_DAY.get(acc, 1)]:
                try:
                    mid, link = post_one(acc, v)
                    st[v["id"]] = {"status": "posted", "ig": mid, "link": link,
                                   "at": dt.datetime.now().isoformat(timespec="seconds")}
                    report.append(f"✅ @{acc}: {v['title'][:50]} → {link}")
                except Exception as e:  # noqa: BLE001
                    tries = st.get(v["id"], {}).get("tries", 0) + 1
                    st[v["id"]] = {"status": "failed" if tries >= 3 else "retry", "tries": tries, "error": str(e)[:300]}
                    report.append(f"❌ @{acc}: {v['title'][:50]}: {str(e)[:160]}")
    save(st)
    out = lines + report
    print("\n".join(out))
    text = " ⏎ ".join(out)
    for k in range(0, len(text), 3800):
        print(f"::notice title=Abgleich YouTube ↔ Instagram {k // 3800 + 1}::{text[k:k + 3800]}")


if __name__ == "__main__":
    main()
