#!/usr/bin/env python3
"""
Instagram-Uploader (Instagram API with Instagram Login, graph.instagram.com).

    python scripts/instagram.py check                      # alle Tokens prüfen
    python scripts/instagram.py refresh                    # Tokens verlängern (60 Tage)
    python scripts/instagram.py reel <konto> <video_url> <caption_datei>

Secrets: IG_TOKEN_CALMHAVEN, IG_TOKEN_MONDMELODIE, IG_TOKEN_LERNBAERCHEN, IG_TOKEN_GUTENACHT
Das Video muss unter einer öffentlichen URL liegen (z. B. GitHub-Release).
"""
import os
import sys
import time

import requests

API = "https://graph.instagram.com/v23.0"
ACCOUNTS = {
    "calmhaven": ("IG_TOKEN_CALMHAVEN", "calmhavenig"),
    "mondmelodie": ("IG_TOKEN_MONDMELODIE", "mondmelodieig"),
    "lernbaerchen": ("IG_TOKEN_LERNBAERCHEN", "lernbaerchenig"),
    "gutenacht": ("IG_TOKEN_GUTENACHT", "gutenachtgeschichteig"),
}


class IGError(RuntimeError):
    pass


def _req(method, path, token, **params):
    params["access_token"] = token
    r = requests.request(method, f"{API}/{path}", params=params if method == "GET" else None,
                         data=params if method != "GET" else None, timeout=120)
    try:
        js = r.json()
    except ValueError:
        js = {"error": {"message": r.text[:300]}}
    if r.status_code >= 400 or "error" in js:
        err = js.get("error", {})
        raise IGError(f"{err.get('message', r.text[:300])} (Code {err.get('code')}/{err.get('error_subcode')})")
    return js


def me(token):
    return _req("GET", "me", token, fields="user_id,username,account_type,media_count")


def token_for(key):
    secret, _ = ACCOUNTS[key]
    tok = os.environ.get(secret)
    if not tok:
        raise IGError(f"Secret {secret} fehlt")
    return tok


def publish_reel(key, video_url, caption, cover_url=None, share_to_feed=True, timeout_s=900):
    """Lädt ein Reel hoch und veröffentlicht es. Gibt (media_id, permalink) zurück."""
    tok = token_for(key)
    info = me(tok)
    expected = ACCOUNTS[key][1]
    if info.get("username") != expected:
        raise IGError(f"Token gehört zu @{info.get('username')}, erwartet @{expected}")
    uid = info["user_id"]
    params = dict(media_type="REELS", video_url=video_url, caption=caption[:2200],
                  share_to_feed="true" if share_to_feed else "false")
    if cover_url:
        params["cover_url"] = cover_url
    cid = _req("POST", f"{uid}/media", tok, **params)["id"]
    t0 = time.time()
    while True:                                   # Instagram lädt und verarbeitet das Video
        st = _req("GET", cid, tok, fields="status_code,status")
        code = st.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise IGError(f"Verarbeitung fehlgeschlagen: {st.get('status')}")
        if time.time() - t0 > timeout_s:
            raise IGError("Zeitüberschreitung bei der Verarbeitung")
        time.sleep(15)
    mid = _req("POST", f"{uid}/media_publish", tok, creation_id=cid)["id"]
    link = _req("GET", mid, tok, fields="permalink").get("permalink")
    return mid, link


def refresh(token):
    r = requests.get("https://graph.instagram.com/refresh_access_token",
                     params={"grant_type": "ig_refresh_token", "access_token": token}, timeout=60)
    js = r.json()
    if "access_token" not in js:
        raise IGError(js.get("error", {}).get("message", r.text[:200]))
    return js["access_token"], js.get("expires_in")


def cmd_check():
    lines, bad = [], 0
    for key, (secret, expected) in ACCOUNTS.items():
        try:
            info = me(token_for(key))
            ok = info.get("username") == expected
            bad += not ok
            lines.append(f"{'✅' if ok else '❌'} {secret}: @{info.get('username')} (erwartet @{expected}), "
                         f"Typ {info.get('account_type')}, {info.get('media_count')} Beiträge")
        except Exception as e:  # noqa: BLE001
            bad += 1
            lines.append(f"❌ {secret}: {str(e)[:160]}")
    print("\n".join(lines))
    print(f"::{'error' if bad else 'notice'} title=IG-Tokencheck::{' | '.join(lines)}")
    return bad


def cmd_media(n=5):
    lines = []
    for key, (secret, expected) in ACCOUNTS.items():
        try:
            tok = token_for(key)
            js = _req("GET", "me/media", tok, fields="timestamp,media_type,media_product_type,permalink,caption", limit=n)
            items = js.get("data", [])
            lines.append(f"## @{expected}: {len(items)} (neueste)")
            for m in items:
                cap = (m.get("caption") or "").split("\n")[0][:60]
                lines.append(f"- {m['timestamp'][:16]} {m.get('media_product_type')} {m.get('permalink')} {cap}")
        except Exception as e:  # noqa: BLE001
            lines.append(f"## @{expected}: FEHLER {str(e)[:160]}")
    print("\n".join(lines))
    print("::notice title=IG-Medien::" + " ⏎ ".join(lines))


def cmd_refresh():
    """Verlängert alle Tokens. Neue Token-Werte werden (falls geändert) per GH_PAT als Secret gespeichert."""
    out = []
    for key, (secret, _) in ACCOUNTS.items():
        try:
            new, exp = refresh(token_for(key))
            changed = new != os.environ.get(secret)
            if changed:
                save_secret(secret, new)
            out.append(f"✅ {secret}: verlängert ({int(exp or 0) // 86400} Tage){' – neu gespeichert' if changed else ''}")
        except Exception as e:  # noqa: BLE001
            out.append(f"❌ {secret}: {str(e)[:160]}")
    print("\n".join(out))
    print(f"::notice title=IG-Refresh::{' | '.join(out)}")


def save_secret(name, value):
    """Speichert ein Secret im Repo (braucht GH_PAT mit Berechtigung 'Secrets: Read and write')."""
    import subprocess
    if not os.environ.get("GH_PAT"):
        raise IGError("GH_PAT fehlt – neuer Token konnte nicht gespeichert werden")
    env = dict(os.environ, GH_TOKEN=os.environ["GH_PAT"])
    subprocess.run(["gh", "secret", "set", name, "--repo", os.environ["GITHUB_REPOSITORY"], "--body", value],
                   check=True, env=env, capture_output=True)


if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "check"
    if c == "check":
        sys.exit(1 if cmd_check() else 0)
    elif c == "refresh":
        cmd_refresh()
    elif c == "media":
        cmd_media()
    elif c == "reel":
        mid, link = publish_reel(sys.argv[2], sys.argv[3], open(sys.argv[4], encoding="utf-8").read())
        print(f"✓ veröffentlicht: {link}")
    else:
        sys.exit(__doc__)
