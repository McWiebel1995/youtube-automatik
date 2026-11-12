#!/usr/bin/env python3
"""
The Clip Lab – Autopilot für Clipping-Kampagnen (Content Rewards / Whop).

  python scripts/cliplab.py probe            Material-Quellen testen (MediaSilo erreichbar?)
  python scripts/cliplab.py cut              Für aktive Kampagnen neue Clips schneiden -> warten auf Freigabe im Studio
  python scripts/cliplab.py post --ids a,b   Freigegebene Clips posten (Instagram + YouTube), TikTok vorbereiten
  python scripts/cliplab.py reject --ids a   Clips verwerfen

Ablauf: Material NUR aus der Kampagne -> ClipWerk-Engine (Kampagnen-Regeln: #Ad, Pflichtzeilen, Logo, keine Musik)
-> Release "cliplab-pending" + data/cliplab/pending.json -> Studio (1 Klick) -> posten -> Links zum Einreichen.
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import requests
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "desktop" / "clipwerk"))
CFG = yaml.safe_load(open(ROOT / "config" / "cliplab.yaml", encoding="utf-8"))
DATA = ROOT / "data" / "cliplab"
PENDING = DATA / "pending.json"
POSTED = DATA / "posted.json"
REPO = os.environ.get("GITHUB_REPOSITORY", "McWiebel1995/youtube-automatik")
MAT_REL, PEND_REL = "cliplab-material", "cliplab-pending"


def note(title, msg):
    print(f"::notice title={title}::{msg[:3500]}")


def load(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def save(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def gh(*args, check=True):
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=check)


def release_assets(tag):
    r = gh("release", "view", tag, "--repo", REPO, "--json", "assets", check=False)
    if r.returncode:
        return []
    return [a["name"] for a in json.loads(r.stdout).get("assets", [])]


def release_upload(tag, path, title):
    if gh("release", "view", tag, "--repo", REPO, check=False).returncode:
        gh("release", "create", tag, "--repo", REPO, "--title", title, "--notes", "Automatisch (The Clip Lab)")
    gh("release", "upload", tag, str(path), "--clobber", "--repo", REPO)


def asset_url(tag, name):
    return f"https://github.com/{REPO}/releases/download/{tag}/{name}"


# ----------------------------------------------------------------------------- Material
def mediasilo_assets(qid):
    """Öffentlicher MediaSilo-Freigabelink -> [(name, url)] der Videos (beste verfügbare Fassung)."""
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0"
    r = s.get(f"https://api.mediasilo.com/v3/quicklinks/{qid}/assets", timeout=60)
    r.raise_for_status()
    out = []
    for a in r.json() if isinstance(r.json(), list) else r.json().get("assets", []):
        if (a.get("type") or "").lower() not in ("video", ""):
            continue
        ders = a.get("derivatives") or []
        best = None
        for d in ders:                                   # Original > hq > proxy
            u = d.get("url") or d.get("source")
            if not u:
                continue
            rank = {"source": 3, "original": 3, "hq": 2, "proxy": 1}.get((d.get("type") or "").lower(), 0)
            if not best or rank > best[0]:
                best = (rank, u)
        if best:
            out.append((a.get("title") or a.get("filename") or a.get("id"), best[1]))
    return out


def material(key, camp, work: Path):
    """Lokale Videodateien für eine Kampagne (Cache im Release cliplab-material)."""
    src = camp.get("source", {})
    have = release_assets(MAT_REL)
    files = []
    prefix = src.get("release_prefix") or key
    words = [w.lower() for w in (src.get("match") or [prefix])]   # Dateiname enthält eines dieser Wörter
    cached = [n for n in have if n.lower().endswith((".mp4", ".mov", ".m4v"))
              and any(w in n.lower() for w in words)]
    if not cached and src.get("mediasilo"):
        for title, url in mediasilo_assets(src["mediasilo"]):
            name = f"{prefix}_{re.sub(r'[^A-Za-z0-9]+', '_', title).strip('_')[:50]}.mp4"
            p = work / name
            with requests.get(url, stream=True, timeout=600) as r:
                r.raise_for_status()
                with open(p, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            release_upload(MAT_REL, p, "The Clip Lab – Kampagnen-Material")
            files.append(p)
            print(f"  Material geladen: {name} ({p.stat().st_size / 1e6:.0f} MB)")
        return files
    for n in cached:
        gh("release", "download", MAT_REL, "--repo", REPO, "--pattern", n, "--dir", str(work), "--clobber")
        files.append(work / n)
    return files


def logo_file(camp, work: Path):
    name = camp.get("logo")
    if not name:
        return ""
    have = release_assets(MAT_REL)
    if name not in have:                             # sonst: Bild, dessen Name alle Wörter enthält (z. B. "warzone logo")
        hits = [n for n in have if n.lower().endswith((".png", ".webp", ".jpg", ".jpeg"))
                and all(w in n.lower() for w in name.lower().replace(".png", "").split())]
        if not hits:
            raise RuntimeError(f"Pflicht-Logo „{name}“ fehlt im Release {MAT_REL}")
        name = hits[0]
    gh("release", "download", MAT_REL, "--repo", REPO, "--pattern", name, "--dir", str(work), "--clobber")
    return str(work / name)


# ----------------------------------------------------------------------------- Schneiden
def today():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


def cmd_cut(only=None):
    import engine
    pend = load(PENDING, [])
    made_today = [p for p in pend if p["created"][:10] == today() and p["status"] != "rejected"]
    budget = int(CFG["accounts"].get("per_day_total", 6)) - len(made_today)
    report = []
    for key, camp in CFG["campaigns"].items():
        if not camp.get("active") or (only and key not in only) or budget <= 0:
            continue
        open_ = [p for p in pend if p["campaign"] == key and p["status"] == "pending"]
        n = min(int(camp.get("reels", 2)), int(camp.get("per_day", 2)) -
                len([p for p in made_today if p["campaign"] == key]), budget)
        if n <= 0 or len(open_) >= 4:                    # nicht auf Halde produzieren
            report.append(f"{key}: übersprungen (heute genug / {len(open_)} warten auf Freigabe)")
            continue
        work = Path(tempfile.mkdtemp(prefix=f"cl_{key}_"))
        try:
            vids = material(key, camp, work)
            if not vids:
                report.append(f"{key}: ⚠ kein Material (bitte hochladen: Release {MAT_REL}, Name {key}_….mp4)")
                continue
            rmin, rmax = camp.get("length", [20, 45])
            used = {p.get("source_window") for p in pend if p["campaign"] == key and p["status"] != "rejected"}
            exclude = [r for p in pend if p["campaign"] == key and p["status"] != "rejected"
                       for r in p.get("ranges", [])] + camp.get("exclude", [])
            s = dict(engine.DEFAULTS, style="clipping", gemini_key=os.environ.get("GEMINI_API_KEY", ""),
                     reels=n, reel_min=rmin, reel_max=rmax, music=False, hook=bool(camp.get("hook", False)),
                     subtitles=True, long_version=False, clip_layout=camp.get("layout", "auto"),
                     clip_ad=True, clip_ad_text=camp.get("ad", "#Ad"), clip_skip_start=camp.get("skip_start", 0),
                     clip_exclude=exclude,
                     clip_required=" | ".join(camp.get("required", [])), clip_credit="",
                     clip_logo=logo_file(camp, work), whisper_model="small",
                     clip_brief=camp.get("brief", "") + ("\nAlready used (pick DIFFERENT moments): " +
                                                        "; ".join(sorted(x for x in used if x)) if used else ""))
            out = work / "out"
            res = engine.process(vids, out, s, log=print)
            for r in res["reels"]:
                mp4 = out / r["file"]
                cid = f"{key}-{dt.datetime.now(dt.timezone.utc):%m%d%H%M}-{len(pend) % 1000:03d}"
                name = f"{cid}.mp4"
                (work / name).write_bytes(mp4.read_bytes())
                release_upload(PEND_REL, work / name, "The Clip Lab – wartet auf Freigabe")
                thumb = out / r["thumb"]
                if thumb.exists():
                    (work / f"{cid}.jpg").write_bytes(thumb.read_bytes())
                    release_upload(PEND_REL, work / f"{cid}.jpg", "The Clip Lab – wartet auf Freigabe")
                tags = [t for t in camp.get("hashtags", [])]
                cap = r["caption"]
                if tags:                                   # Kampagnen-Hashtags statt der KI-Hashtags (max. 3 nach #Ad)
                    lines = cap.split("\n")
                    ad = camp.get("ad", "#Ad")
                    keep = lines[:lines.index(ad) + 1] if ad in lines else lines
                    cap = "\n".join(keep + [" ".join(tags[:3])])
                pend.append({"id": cid, "campaign": key, "campaign_name": camp["name"], "status": "pending",
                             "created": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                             "video": asset_url(PEND_REL, name), "thumb": asset_url(PEND_REL, f"{cid}.jpg"),
                             "duration": r["duration"], "caption": cap, "platforms": camp.get("platforms", []),
                             "source_window": r.get("hook") or r["file"], "ranges": r.get("ranges", [])})
                save(PENDING, pend)
                budget -= 1
                report.append(f"{key}: ✓ {cid} ({r['duration']:.0f}s)")
        except Exception as e:  # noqa: BLE001
            report.append(f"{key}: ✗ {str(e)[:300]}")
            print(f"✗ {key}: {e}")
        finally:
            subprocess.run(["rm", "-rf", str(work)])
    note("Clip Lab – Schneiden", " ⏎ ".join(report) or "nichts zu tun")


# ----------------------------------------------------------------------------- Posten
def yt_post(item, path):
    import upload
    tok = os.environ.get(CFG["accounts"]["youtube"])
    if not tok:
        raise RuntimeError(f"Secret {CFG['accounts']['youtube']} fehlt")
    yt = upload.service(tok)
    first = item["caption"].split("\n")[0]
    title = re.sub(r"\s+", " ", re.sub(r"#\w+", "", first)).strip()[:90] or item["campaign_name"]
    meta = {"title": title + " #Shorts", "description": item["caption"],
            "tags": [t.lstrip("#") for t in re.findall(r"#\w+", item["caption"])][:10]}
    ch = {"name": "The Clip Lab", "privacy": "public", "category_id": "20", "language": "en"}
    vid = upload.upload(yt, path, meta, ch)
    return f"https://youtube.com/shorts/{vid}"


def cmd_post(ids, edits=None):
    import instagram
    pend = load(PENDING, [])
    posted = load(POSTED, [])
    report = []
    for item in pend:
        if item["id"] not in ids or item["status"] not in ("pending", "approved"):
            continue
        if edits and edits.get(item["id"]):
            item["caption"] = edits[item["id"]]
        links = {}
        tmp = Path(tempfile.mkdtemp()) / f"{item['id']}.mp4"
        with requests.get(item["video"], stream=True, timeout=600) as r:
            r.raise_for_status()
            tmp.write_bytes(r.content)
        if "instagram" in item["platforms"]:
            try:
                _, link = instagram.publish_reel(CFG["accounts"]["instagram"], item["video"], item["caption"],
                                                 cover_url=item.get("thumb"))
                links["instagram"] = link
            except Exception as e:  # noqa: BLE001
                links["instagram_error"] = str(e)[:200]
        if "youtube" in item["platforms"]:
            try:
                links["youtube"] = yt_post(item, tmp)
            except Exception as e:  # noqa: BLE001
                links["youtube_error"] = str(e)[:200]
        if "tiktok" in item["platforms"]:
            links["tiktok"] = "manuell"                  # TikTok-API postet ohne Prüfung nur privat
        item.update(status="posted", posted=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                    links=links, submit_by=(dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=30)).isoformat(
                        timespec="minutes"))
        posted.append(item)
        report.append(f"{item['id']}: " + ", ".join(f"{k}={v}" for k, v in links.items()))
    save(PENDING, pend)
    save(POSTED, posted[-500:])
    note("Clip Lab – Gepostet", " ⏎ ".join(report) or "nichts freigegeben")


def cmd_approve(ids, edits=None):
    """Freigeben -> wird zur nächsten US-Postzeit (Cron) automatisch gepostet."""
    pend = load(PENDING, [])
    for item in pend:
        if item["id"] in ids and item["status"] == "pending":
            item["status"] = "approved"
            if edits and edits.get(item["id"]):
                item["caption"] = edits[item["id"]]
    save(PENDING, pend)
    note("Clip Lab – Freigegeben", ", ".join(ids))


def cmd_post_due():
    """US-Postzeit: alle freigegebenen Clips posten (max. 2 pro Lauf, Rest beim nächsten Termin)."""
    ids = [p["id"] for p in load(PENDING, []) if p["status"] == "approved"][:2]
    if ids:
        cmd_post(ids)
    else:
        note("Clip Lab", "nichts freigegeben")


def cmd_reject(ids):
    pend = load(PENDING, [])
    for item in pend:
        if item["id"] in ids and item["status"] == "pending":
            item["status"] = "rejected"
    save(PENDING, pend)


def cmd_fetch(url, name):
    """Freigegebenes Kampagnen-Material (signierter Download-Link aus dem Kampagnen-Ordner) im Release ablegen."""
    work = Path(tempfile.mkdtemp())
    p = work / name
    with requests.get(url, stream=True, timeout=900) as r:
        r.raise_for_status()
        with open(p, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    release_upload(MAT_REL, p, "The Clip Lab – Kampagnen-Material")
    note("Clip Lab – Material", f"{name}: {p.stat().st_size / 1e6:.0f} MB gespeichert")


def cmd_probe():
    out = []
    if gh("release", "view", MAT_REL, "--repo", REPO, check=False).returncode:
        gh("release", "create", MAT_REL, "--repo", REPO, "--prerelease", "--title", "The Clip Lab – Kampagnen-Material",
           "--notes", "Nur freigegebenes Kampagnen-Material (Content Rewards). Dateien einfach hierher ziehen.")
        out.append("Material-Release angelegt")
    for key, camp in CFG["campaigns"].items():
        q = (camp.get("source") or {}).get("mediasilo")
        if not q:
            continue
        try:
            a = mediasilo_assets(q)
            out.append(f"{key}: {len(a)} Videos – " + "; ".join(t for t, _ in a)[:300])
        except Exception as e:  # noqa: BLE001
            out.append(f"{key}: ✗ {str(e)[:200]}")
    out.append("Material-Release: " + ", ".join(release_assets(MAT_REL))[:500])
    try:                                                 # Zugänge prüfen (ohne Token-Inhalt)
        import upload
        tok = os.environ.get(CFG["accounts"]["youtube"])
        if tok:
            ch = upload.service(tok).channels().list(part="snippet", mine=True).execute()["items"][0]["snippet"]
            out.append(f"YouTube: ✓ Kanal „{ch['title']}“")
        else:
            out.append("YouTube: Secret fehlt")
    except Exception as e:  # noqa: BLE001
        out.append(f"YouTube: ✗ {str(e)[:200]}")
    try:
        import instagram
        if "cliplab" in instagram.ACCOUNTS:
            out.append(f"Instagram: ✓ @{instagram.me(instagram.token_for('cliplab')).get('username')}")
        else:
            out.append("Instagram: Secret fehlt")
    except Exception as e:  # noqa: BLE001
        out.append(f"Instagram: ✗ {str(e)[:200]}")
    note("Clip Lab – Probe", " ⏎ ".join(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["probe", "cut", "post", "reject", "fetch", "approve", "due"])
    ap.add_argument("--ids", default="")
    ap.add_argument("--only", default="")
    ap.add_argument("--edits", default="")              # JSON {id: caption}
    ap.add_argument("--url", default="")
    ap.add_argument("--name", default="")
    a = ap.parse_args()
    ids = [x for x in a.ids.split(",") if x]
    if a.mode == "probe":
        cmd_probe()
    elif a.mode == "cut":
        cmd_cut([x for x in a.only.split(",") if x] or None)
    elif a.mode == "fetch":
        cmd_fetch(a.url or os.environ.get("FETCH_URL", ""), a.name)
    elif a.mode == "approve":
        cmd_approve(ids, json.loads(a.edits) if a.edits else None)
    elif a.mode == "due":
        cmd_post_due()
    elif a.mode == "post":
        cmd_post(ids, json.loads(a.edits) if a.edits else None)
    else:
        cmd_reject(ids)


if __name__ == "__main__":
    main()
