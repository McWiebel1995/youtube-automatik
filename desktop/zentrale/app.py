#!/usr/bin/env python3
"""
Cicco Zentrale – Windows-Programm: 3D-Insel mit allen Projekten, Mitarbeitern und Aufträgen.

  python app.py              # Programm starten
  python app.py --selftest   # ohne Fenster: Katalog + GitHub-Verbindung prüfen (für den Build)

Daten bleiben auf diesem PC (%APPDATA%/CiccoZentrale). Der GitHub-Schlüssel liegt in der Windows-Anmeldeinformations-
verwaltung (keyring), nie in einer Datei.
"""
import datetime as dt
import json
import os
import sys
import webbrowser
from pathlib import Path

import requests

HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
sys.path.insert(0, str(HERE))
import jobs  # noqa: E402

DATA = Path(os.environ.get("APPDATA", Path.home() / ".config")) / "CiccoZentrale"
DATA.mkdir(parents=True, exist_ok=True)
TASKS = DATA / "tasks.json"
HISTORY = DATA / "history.json"
API = f"https://api.github.com/repos/{jobs.REPO}"
PAGES = "https://mcwiebel1995.github.io/youtube-automatik"
ALLOWED = ("https://api.github.com/", PAGES + "/")
KEYRING = ("CiccoZentrale", "github")


def _token():
    try:
        import keyring
        return keyring.get_password(*KEYRING)
    except Exception:  # noqa: BLE001
        return None


def _headers():
    h = {"Accept": "application/vnd.github+json", "User-Agent": "CiccoZentrale"}
    t = _token()
    if t:
        h["Authorization"] = f"Bearer {t}"
    return h


def _load(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def _save(p, data):
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


class Api:
    """Wird von der Oberfläche (web/index.html) über window.pywebview.api aufgerufen."""

    def catalog(self):
        return {"depts": jobs.DEPTS, "has_token": bool(_token())}

    # --- Live-Daten (nur lesend)
    def fetch(self, url):
        if not url.startswith(ALLOWED):
            return {"error": "Adresse nicht erlaubt"}
        try:
            r = requests.get(url, headers=_headers() if url.startswith(ALLOWED[0]) else {}, timeout=20)
            return r.json() if r.ok else {"error": f"HTTP {r.status_code}"}
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)[:200]}

    # --- Aufträge
    def dispatch(self, job_id, approved=False):
        j = jobs.find(job_id)
        if not j:
            return {"ok": False, "msg": "Unbekannter Handgriff"}
        if j["external"] and not approved:
            return {"ok": False, "msg": "Braucht deine Freigabe"}
        if not _token():
            return {"ok": False, "msg": "Kein GitHub-Schlüssel hinterlegt (Einstellungen)"}
        started = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        r = requests.post(f"{API}/actions/workflows/{j['workflow']}/dispatches", headers=_headers(), timeout=20,
                          json={"ref": "main", "inputs": j["inputs"]})
        ok = r.status_code == 204
        hist = _load(HISTORY, [])
        hist.append({"job": job_id, "label": j["label"], "workflow": j["workflow"], "at": started, "ok": ok,
                     "msg": "" if ok else r.text[:200]})
        _save(HISTORY, hist[-300:])
        if ok:
            return {"ok": True, "started": started, "workflow": j["workflow"]}
        return {"ok": False, "msg": {401: "Schlüssel ungültig", 403: "Schlüssel ohne Actions-Schreibrecht",
                                     404: "Workflow nicht gefunden", 422: "Eingaben passen nicht"}.get(r.status_code,
                                                                                                      f"GitHub {r.status_code}")}

    def history(self):
        return _load(HISTORY, [])[-60:]

    # --- Aufgabenliste (lokal)
    def tasks(self):
        if not TASKS.exists():
            _save(TASKS, [dict(t, id=i, done=False) for i, t in enumerate(jobs.START_TASKS)])
        return _load(TASKS, [])

    def save_tasks(self, tasks):
        _save(TASKS, tasks)
        return True

    # --- Einstellungen
    def set_token(self, token):
        token = (token or "").strip()
        if not token.startswith(("github_pat_", "ghp_")):
            return {"ok": False, "msg": "Das sieht nicht wie ein GitHub-Schlüssel aus"}
        r = requests.get(API, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}, timeout=20)
        if not r.ok:
            return {"ok": False, "msg": f"GitHub lehnt den Schlüssel ab ({r.status_code})"}
        import keyring
        keyring.set_password(*KEYRING, token)
        return {"ok": True}

    def clear_token(self):
        try:
            import keyring
            keyring.delete_password(*KEYRING)
        except Exception:  # noqa: BLE001
            pass
        return True

    def open(self, url):
        if url.startswith(("https://github.com/", "https://www.youtube.com/", "https://youtu.be/", "https://www.instagram.com/",
                           "https://studio.youtube.com/", PAGES)):
            webbrowser.open(url)
        return True


def selftest():
    api = Api()
    lines = [f"Abteilungen: {len(jobs.DEPTS)}, Handgriffe: {sum(len(w.get('jobs', [])) for d in jobs.DEPTS for w in d['team'])}"]
    r = api.fetch(f"{API}/actions/runs?per_page=5")
    lines.append(f"GitHub: {'OK, ' + str(len(r.get('workflow_runs', []))) + ' Läufe' if 'workflow_runs' in r else r}")
    s = api.fetch(f"{PAGES}/status.json")
    lines.append(f"Studio-Daten: {'OK, ' + str(len(s.get('channels', []))) + ' Kanäle' if 'channels' in s else s}")
    lines.append(f"Aufgaben: {len(api.tasks())}")
    lines.append(f"Oberfläche: {'OK' if (HERE / 'web' / 'index.html').exists() else 'FEHLT'}, "
                 f"three.js: {'OK' if (HERE / 'web' / 'vendor' / 'three.min.js').exists() else 'FEHLT'}")
    Path("selftest.log").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


def main():
    if "--selftest" in sys.argv:
        return selftest()
    import webview
    webview.create_window("Cicco Zentrale", str(HERE / "web" / "index.html"), js_api=Api(),
                          width=1440, height=900, min_size=(900, 600), background_color="#0f1424")
    webview.start()


if __name__ == "__main__":
    main()
