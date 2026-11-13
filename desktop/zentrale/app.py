#!/usr/bin/env python3
"""
Cicco Zentrale – Windows-Programm: Cockpit für alle Projekte, Konten, Freigaben und Freitext-Aufträge (+ 3D-Stadt).

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
MAILCFG = DATA / "postfach.json"                        # Server, Port, Benutzer – Passwort nur in Windows (keyring)
LOCAL_ACC = DATA / "zugaenge.json"                      # nur Namen/Links/Art – NIE Schlüssel oder Passwörter
API = f"https://api.github.com/repos/{jobs.REPO}"
PAGES = "https://mcwiebel1995.github.io/youtube-automatik"
ALLOWED = ("https://api.github.com/", PAGES + "/")
KEYRING = ("CiccoZentrale", "github")
ORDERS = "McWiebel1995/cicco-zentrale"                 # privates Repo: jeder Auftrag ist ein Ticket (Issue)
OAPI = f"https://api.github.com/repos/{ORDERS}"


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
        return {"depts": jobs.DEPTS, "has_token": bool(_token()), "orders_repo": ORDERS}

    # --- Freitext-Aufträge (Issues im privaten Repo, Claude arbeitet sie stündlich ab)
    def _gh(self, method, url, **kw):
        if not _token():
            return None, "Kein GitHub-Schlüssel hinterlegt (Einstellungen)"
        try:
            r = requests.request(method, url, headers=_headers(), timeout=20, **kw)
        except Exception as e:  # noqa: BLE001
            return None, f"Keine Verbindung: {str(e)[:120]}"
        if r.status_code in (401, 403):
            return None, "Schlüssel hat keinen Zugriff auf cicco-zentrale (Issues: Lesen & Schreiben)"
        if r.status_code == 404:
            return None, "Repo cicco-zentrale nicht gefunden – bitte anlegen (privat)"
        if not r.ok:
            return None, f"GitHub {r.status_code}"
        return (r.json() if r.content else {}), None

    def orders(self):
        js, err = self._gh("GET", f"{OAPI}/issues", params={"labels": "auftrag", "state": "all", "per_page": 50})
        if err:
            return {"error": err}
        items = [{"number": i["number"], "title": i["title"], "state": i["state"], "created_at": i["created_at"],
                  "comments": i["comments"], "labels": [l["name"] for l in i["labels"]],
                  "project": next((l["name"][8:] for l in i["labels"] if l["name"].startswith("projekt:")), "")}
                 for i in js if "pull_request" not in i]
        return {"items": items}

    def order_create(self, title, body, project=""):
        title, body = (title or "").strip()[:120], (body or "").strip()[:8000]
        if not title:
            return {"ok": False, "msg": "Leerer Auftrag"}
        labels = ["auftrag"] + ([f"projekt:{project}"] if project else [])
        js, err = self._gh("POST", f"{OAPI}/issues", json={"title": title, "body": body, "labels": labels})
        return {"ok": True, "number": js["number"]} if not err else {"ok": False, "msg": err}

    def order_thread(self, number):
        i, err = self._gh("GET", f"{OAPI}/issues/{int(number)}")
        if err:
            return {"error": err}
        cs, err = self._gh("GET", f"{OAPI}/issues/{int(number)}/comments", params={"per_page": 100})
        if err:
            return {"error": err}
        me = i["user"]["login"]
        return {"number": i["number"], "title": i["title"], "state": i["state"], "created_at": i["created_at"],
                "body": i.get("body") or "", "comments": [{"body": c["body"], "created_at": c["created_at"],
                                                          "mine": c["user"]["login"] == me and not c["body"].startswith("🤖")}
                                                         for c in cs]}

    def order_reply(self, number, text):
        text = (text or "").strip()[:8000]
        if not text:
            return {"ok": False, "msg": "Leer"}
        _, err = self._gh("POST", f"{OAPI}/issues/{int(number)}/comments", json={"body": text})
        if err:
            return {"ok": False, "msg": err}
        self._gh("DELETE", f"{OAPI}/issues/{int(number)}/labels/r%C3%BCckfrage")   # Antwort da -> wieder bei Claude
        self._gh("PATCH", f"{OAPI}/issues/{int(number)}", json={"state": "open"})
        return {"ok": True}

    # --- Zugänge: Schlüssel gehen verschlüsselt als GitHub-Secret raus, lokal bleibt nur die Beschreibung
    def access_list(self):
        names = []
        js, err = self._gh("GET", f"{API}/actions/secrets", params={"per_page": 100})
        if not err:
            names = [x["name"] for x in js.get("secrets", [])]
        return {"local": _load(LOCAL_ACC, []), "secrets": names, "secrets_error": err or ""}

    def access_add(self, kind, label, project, secret_name="", value="", url=""):
        import re
        label = (label or "").strip()[:80]
        if not label:
            return {"ok": False, "msg": "Name fehlt"}
        entry = {"kind": kind, "label": label, "project": project or "", "added": dt.date.today().isoformat()}
        if kind == "key":
            secret_name = (secret_name or "").strip().upper()
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,60}", secret_name) or secret_name.startswith("GITHUB_"):
                return {"ok": False, "msg": "Secret-Name: nur A–Z, 0–9 und _ (z. B. LEXOFFICE_API_KEY)"}
            if not value or len(value) > 20000:
                return {"ok": False, "msg": "Schlüssel fehlt"}
            pk, err = self._gh("GET", f"{API}/actions/secrets/public-key")
            if err:
                return {"ok": False, "msg": err if "Schlüssel" in err else "Dein Zentrale-Schlüssel braucht das Recht „Secrets: Read and write“"}
            from base64 import b64decode, b64encode
            from nacl import encoding, public    # libsodium – wie von GitHub verlangt
            box = public.SealedBox(public.PublicKey(pk["key"].encode(), encoding.Base64Encoder()))
            enc = b64encode(box.encrypt(value.encode("utf-8"))).decode()
            _, err = self._gh("PUT", f"{API}/actions/secrets/{secret_name}", json={"encrypted_value": enc, "key_id": pk["key_id"]})
            del value, enc
            if err:
                return {"ok": False, "msg": "Speichern fehlgeschlagen: " + err}
            entry["secret"] = secret_name
        elif kind == "chrome":
            url = (url or "").strip()
            if url and not url.startswith("https://"):
                return {"ok": False, "msg": "Link muss mit https:// beginnen"}
            entry["url"] = url
        else:
            return {"ok": False, "msg": "Unbekannte Art"}
        acc = [a for a in _load(LOCAL_ACC, []) if a.get("label") != label]
        _save(LOCAL_ACC, acc + [entry])
        return {"ok": True}

    def access_remove(self, label):
        _save(LOCAL_ACC, [a for a in _load(LOCAL_ACC, []) if a.get("label") != label])
        return True

    # --- Posteingang (IMAP, nur lesend: Mails bleiben ungelesen)
    def _imap(self):
        import imaplib
        cfg = _load(MAILCFG, {})
        if not cfg.get("host"):
            return None, None, "nicht eingerichtet"
        import keyring
        pw = keyring.get_password("CiccoZentrale", "mail:" + cfg["user"])
        if not pw:
            return None, cfg, "Passwort fehlt"
        try:
            m = imaplib.IMAP4_SSL(cfg["host"], int(cfg.get("port", 993)), timeout=25)
            m.login(cfg["user"], pw)
            m.select("INBOX", readonly=True)
            return m, cfg, None
        except Exception as e:  # noqa: BLE001
            return None, cfg, f"Anmeldung fehlgeschlagen: {str(e)[:120]}"

    def mail_config(self):
        cfg = _load(MAILCFG, {})
        return {"host": cfg.get("host", "ha01s007-cl.org-dns.com"), "port": cfg.get("port", 993),
                "user": cfg.get("user", "info@cicco-fam.de"), "ready": bool(cfg.get("host"))}

    def mail_setup(self, host, port, user, password):
        import imaplib
        host, user = (host or "").strip(), (user or "").strip()
        try:
            m = imaplib.IMAP4_SSL(host, int(port or 993), timeout=25)
            m.login(user, password)
            m.logout()
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "msg": f"Anmeldung fehlgeschlagen: {str(e)[:150]}"}
        import keyring
        keyring.set_password("CiccoZentrale", "mail:" + user, password)
        _save(MAILCFG, {"host": host, "port": int(port or 993), "user": user})
        return {"ok": True}

    def mail_remove(self):
        cfg = _load(MAILCFG, {})
        try:
            import keyring
            keyring.delete_password("CiccoZentrale", "mail:" + cfg.get("user", ""))
        except Exception:  # noqa: BLE001
            pass
        MAILCFG.unlink(missing_ok=True)
        return True

    def mail_list(self, n=40):
        import email
        from email.header import decode_header, make_header
        from email.utils import parsedate_to_datetime, parseaddr
        m, cfg, err = self._imap()
        if err:
            return {"error": err}
        try:
            _, data = m.uid("search", None, "ALL")
            uids = data[0].split()[-int(n):]
            out = []
            if uids:
                _, rows = m.uid("fetch", b",".join(uids), "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                for i in range(0, len(rows)):
                    r = rows[i]
                    if not isinstance(r, tuple):
                        continue
                    meta = r[0].decode(errors="replace")
                    uid = meta.split("UID ")[1].split()[0] if "UID " in meta else ""
                    h = email.message_from_bytes(r[1])
                    dec = lambda v: str(make_header(decode_header(v or "")))  # noqa: E731
                    name, addr = parseaddr(dec(h.get("From")))
                    try:
                        when = parsedate_to_datetime(h.get("Date")).isoformat()
                    except Exception:  # noqa: BLE001
                        when = ""
                    out.append({"uid": uid, "from": name or addr, "addr": addr, "subject": dec(h.get("Subject")) or "(kein Betreff)",
                                "date": when, "seen": "\\Seen" in meta})
            out.sort(key=lambda x: int(x["uid"] or 0), reverse=True)
            return {"items": out, "user": cfg["user"]}
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)[:200]}
        finally:
            try:
                m.logout()
            except Exception:  # noqa: BLE001
                pass

    def mail_read(self, uid):
        import email
        import html as H
        import re
        from email.header import decode_header, make_header
        m, cfg, err = self._imap()
        if err:
            return {"error": err}
        try:
            _, rows = m.uid("fetch", str(int(uid)).encode(), "(BODY.PEEK[])")
            msg = email.message_from_bytes(rows[0][1])
            text, html_part, files = "", "", []
            for part in msg.walk():
                ct, disp = part.get_content_type(), str(part.get("Content-Disposition") or "")
                if "attachment" in disp:
                    files.append(str(make_header(decode_header(part.get_filename() or "Anhang"))))
                elif ct == "text/plain" and not text:
                    text = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
                elif ct == "text/html" and not html_part:
                    html_part = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
            if not text and html_part:               # HTML nur als Text zeigen (keine Skripte, keine Tracking-Bilder)
                t = re.sub(r"(?is)<(script|style).*?</\1>", "", html_part)
                t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", t)
                text = H.unescape(re.sub(r"<[^>]+>", "", t))
            text = re.sub(r"\n{3,}", "\n\n", text).strip()[:30000]
            dec = lambda v: str(make_header(decode_header(v or "")))  # noqa: E731
            return {"from": dec(msg.get("From")), "to": dec(msg.get("To")), "subject": dec(msg.get("Subject")),
                    "date": msg.get("Date"), "text": text, "files": files}
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)[:200]}
        finally:
            try:
                m.logout()
            except Exception:  # noqa: BLE001
                pass

    def mail_send(self, to, subject, body, reply_uid=None):
        """Antwort/Neue Mail von der Postfach-Adresse senden (SMTP SSL 465) + Kopie in „Gesendet“."""
        import email.utils
        import smtplib
        import time
        from email.message import EmailMessage
        import keyring
        cfg = _load(MAILCFG, {})
        to, subject, body = (to or "").strip(), (subject or "").strip()[:200], body or ""
        if not cfg.get("host"):
            return {"ok": False, "msg": "Postfach nicht eingerichtet"}
        if "@" not in to or "\n" in to or len(to) > 200 or not body.strip():
            return {"ok": False, "msg": "Empfänger oder Text fehlt"}
        pw = keyring.get_password("CiccoZentrale", "mail:" + cfg["user"])
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = cfg["user"], to, subject
        msg["Date"], msg["Message-ID"] = email.utils.formatdate(localtime=True), email.utils.make_msgid(domain=cfg["user"].split("@")[1])
        if reply_uid:                                   # Antwort sauber an den Verlauf hängen
            m, _, err = self._imap()
            if not err:
                try:
                    _, rows = m.uid("fetch", str(int(reply_uid)).encode(), "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID REFERENCES)])")
                    h = email.message_from_bytes(rows[0][1])
                    if h.get("Message-ID"):
                        msg["In-Reply-To"] = h["Message-ID"]
                        msg["References"] = ((h.get("References") or "") + " " + h["Message-ID"]).strip()
                finally:
                    m.logout()
        msg.set_content(body)
        try:
            with smtplib.SMTP_SSL(cfg.get("smtp_host", cfg["host"]), int(cfg.get("smtp_port", 465)), timeout=30) as sm:
                sm.login(cfg["user"], pw)
                sm.send_message(msg)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "msg": f"Senden fehlgeschlagen: {str(e)[:150]}"}
        try:                                            # Kopie in den Gesendet-Ordner (wie Outlook)
            import imaplib
            m = imaplib.IMAP4_SSL(cfg["host"], int(cfg.get("port", 993)), timeout=25)
            m.login(cfg["user"], pw)
            _, boxes = m.list()
            names = [b.decode(errors="replace").split(' "/" ')[-1].split(' "." ')[-1].strip('"') for b in boxes or []]
            sent = next((n for n in names if n.lower().split(".")[-1] in ("sent", "gesendet", "sent items", "sent messages")), None)
            if sent:
                m.append(f'"{sent}"', "\\Seen", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
            m.logout()
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True}

    def notify(self, title, text):
        """Windows-Benachrichtigung (unten rechts)."""
        try:
            from winotify import Notification
            Notification(app_id="Cicco Zentrale", title=str(title)[:80], msg=str(text)[:200]).show()
        except Exception:  # noqa: BLE001
            pass
        return True

    # --- Clip-Freigabe (The Clip Lab): nur diese zwei festen Aktionen
    def clip_decide(self, ids, action, edits=None):
        if action not in ("approve", "reject") or not ids or not all(isinstance(i, str) and len(i) < 60 for i in ids):
            return {"ok": False, "msg": "Ungültig"}
        inputs = {"mode": action, "ids": ",".join(ids)}
        if edits:
            inputs["edits"] = json.dumps(edits, ensure_ascii=False)
        _, err = self._gh("POST", f"{API}/actions/workflows/cliplab.yml/dispatches", json={"ref": "main", "inputs": inputs})
        if err == "Repo cicco-zentrale nicht gefunden – bitte anlegen (privat)":
            err = "Workflow nicht gefunden"
        return {"ok": not err, "msg": err or ""}

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
                           "https://studio.youtube.com/", "https://contentrewards.com/", "https://www.tiktok.com/", "https://lovable.dev/", "mailto:", PAGES)):
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
    a = api.fetch(f"{PAGES}/accounts.json")
    lines.append(f"Konten-Ampel: {'OK, ' + str(len(a.get('accounts', []))) + ' Konten' if 'accounts' in a else a}")
    lines.append(f"Aufträge: {api.orders().get('error', 'OK')}")
    lines.append(f"Oberfläche: {'OK' if all((HERE / 'web' / f).exists() for f in ('index.html', 'cockpit.js', 'stadt.html')) else 'FEHLT'}, "
                 f"three.js: {'OK' if (HERE / 'web' / 'vendor' / 'three.min.js').exists() else 'FEHLT'}")
    Path("selftest.log").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


def _unblock():
    """Windows markiert entpackte Dateien aus dem Internet (Zone.Identifier). .NET lädt solche DLLs nicht
    ("Failed to resolve Python.Runtime.Loader.Initialize") -> Markierung bei unseren eigenen Dateien entfernen."""
    if sys.platform != "win32":
        return
    for root, _dirs, files in os.walk(HERE):
        for f in files:
            if f.lower().endswith((".dll", ".pyd", ".exe")):
                try:
                    os.remove(os.path.join(root, f) + ":Zone.Identifier")
                except OSError:
                    pass


def main():
    if "--selftest" in sys.argv:
        return selftest()
    _unblock()
    import webview
    webview.create_window("Cicco Zentrale", str(HERE / "web" / "index.html"), js_api=Api(),
                          width=1440, height=900, min_size=(900, 600), background_color="#0f1424")
    webview.start()


if __name__ == "__main__":
    main()
