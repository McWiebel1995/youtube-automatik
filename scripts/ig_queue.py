#!/usr/bin/env python3
"""
Warteschlange für Instagram-Reels.

  Produktion (Kinder/Relax):  ig_queue.add("mondmelodie", "/pfad/short.mp4", caption)
      -> lädt das Video als öffentlichen Release-Anhang hoch (Tag "ig-media") und merkt es vor
  Abends (Workflow instagram-post): python scripts/ig_queue.py post
      -> veröffentlicht alles Vorgemerkte als Reel

Ablage: data/ig_queue/<id>.json (eine Datei pro Reel – parallele Läufe überschreiben sich nicht)
"""
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QDIR = ROOT / "data" / "ig_queue"
OLD = ROOT / "data" / "instagram_queue.json"
TAG = "ig-media"


def now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load():
    items = []
    if OLD.exists():                                  # alte Sammeldatei einmalig übernehmen
        QDIR.mkdir(parents=True, exist_ok=True)
        for it in json.loads(OLD.read_text(encoding="utf-8")):
            (QDIR / f"{it['id']}.json").write_text(json.dumps(it, ensure_ascii=False, indent=1), encoding="utf-8")
        OLD.unlink()
    for f in sorted(QDIR.glob("*.json")) if QDIR.exists() else []:
        items.append(json.loads(f.read_text(encoding="utf-8")))
    items.sort(key=lambda x: x.get("created_at", ""))
    return items


def save_item(item):
    QDIR.mkdir(parents=True, exist_ok=True)
    (QDIR / f"{item['id']}.json").write_text(json.dumps(item, ensure_ascii=False, indent=1), encoding="utf-8")


def upload_public(path: Path, name: str) -> str:
    repo = os.environ["GITHUB_REPOSITORY"]
    if subprocess.run(["gh", "release", "view", TAG, "--repo", repo], capture_output=True).returncode:
        subprocess.run(["gh", "release", "create", TAG, "--repo", repo, "--title", "Instagram-Medien",
                        "--notes", "Automatisch abgelegte Videos für Instagram-Reels.", "--prerelease"],
                       check=True, capture_output=True)
    tmp = path.with_name(name)
    if tmp != path:
        tmp.write_bytes(path.read_bytes())
    subprocess.run(["gh", "release", "upload", TAG, str(tmp), "--clobber", "--repo", repo], check=True, capture_output=True)
    return f"https://github.com/{repo}/releases/download/{TAG}/{name}"


def add(account, video, caption, name=None):
    """video = lokaler Pfad oder öffentliche URL. Gibt den Eintrag zurück (oder None, wenn nicht möglich)."""
    try:
        if not str(video).startswith("http"):
            if not (os.environ.get("GITHUB_REPOSITORY") and os.environ.get("GH_TOKEN")):
                print("  (Instagram: kein GitHub-Kontext – nicht vorgemerkt)")
                return None
            stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            video = upload_public(Path(video), name or f"{account}-{stamp}.mp4")
        item = {"id": f"{account}-{int(dt.datetime.now().timestamp())}", "account": account,
                "video_url": video, "caption": caption, "created_at": now(), "status": "pending"}
        save_item(item)
        print(f"  📸 Instagram vorgemerkt: @{account}")
        return item
    except Exception as e:  # noqa: BLE001 – Instagram darf die YouTube-Produktion nie stoppen
        print(f"  ⚠ Instagram-Vormerkung fehlgeschlagen: {e}")
        return None


def _recent_captions(instagram, account):
    """Erste Zeilen der letzten Beiträge – Schutz gegen Doppel-Posts."""
    try:
        js = instagram._req("GET", "me/media", instagram.token_for(account), fields="caption,timestamp", limit=12)
        return {(m.get("caption") or "").strip()[:120] for m in js.get("data", [])}
    except Exception:  # noqa: BLE001
        return set()


def post(limit_per_account=1):
    import instagram
    items, done, report = load(), {}, []
    recent = {}
    for it in items:
        if it.get("status") != "pending":
            continue
        if done.get(it["account"], 0) >= limit_per_account:
            continue
        if it["account"] not in recent:
            recent[it["account"]] = _recent_captions(instagram, it["account"])
        if it["caption"].strip()[:120] in recent[it["account"]]:
            it.update(status="posted", note="bereits auf Instagram (Doppel-Post verhindert)")
            save_item(it)
            report.append(f"⏭ @{it['account']}: schon gepostet – übersprungen")
            continue
        try:
            mid, link = instagram.publish_reel(it["account"], it["video_url"], it["caption"])
            it.update(status="posted", posted_at=now(), media_id=mid, permalink=link)
            report.append(f"✅ @{it['account']}: {link}")
        except Exception as e:  # noqa: BLE001
            it["tries"] = it.get("tries", 0) + 1
            it["error"] = str(e)[:300]
            if it["tries"] >= 3:
                it["status"] = "failed"
            report.append(f"❌ @{it['account']}: {str(e)[:200]}")
        done[it["account"]] = done.get(it["account"], 0) + 1
        save_item(it)
    msg = " | ".join(report) or "nichts zu posten"
    print(msg.replace(" | ", "\n"))
    print(f"::notice title=Instagram::{msg}")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    cmd = sys.argv[1] if len(sys.argv) > 1 else "post"
    if cmd == "post":
        post()
    elif cmd == "add":                                    # python ig_queue.py add <konto> <url> <caption>
        add(sys.argv[2], sys.argv[3], sys.argv[4])
