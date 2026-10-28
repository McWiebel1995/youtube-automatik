"""Kleiner Gemini-Client (REST) mit Modell-Fallback und Wiederholung bei Überlastung."""
import json
import os
import re
import time

import requests

_post_raw = requests.post


def _post(*a, **kw):
    """requests.post mit Wiederholung bei Verbindungsabbrüchen."""
    for attempt in range(4):
        try:
            return _post_raw(*a, **kw)
        except (requests.ConnectionError, requests.Timeout):
            if attempt == 3:
                raise
            time.sleep(10 * (attempt + 1))

DEFAULT_MODELS = ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash"]


class QuotaError(RuntimeError):
    """Gratis-Limit erreicht – später erneut."""


def _parse_json(txt):
    """JSON aus der Antwort holen; bei kleinen Fehlern reparieren (json-repair). None, wenn hoffnungslos."""
    t = txt.strip()
    starts = [i for i in (t.find("{"), t.find("[")) if i >= 0]
    if not starts:
        return None
    t = t[min(starts):]
    try:
        return json.JSONDecoder().raw_decode(t)[0]       # ignoriert Text/zweites JSON danach
    except ValueError:
        pass
    fixed = re.sub(r'„([^"„“\n]{0,200})"', r"„\1“", t)       # deutsches „…" mit falschem Schlusszeichen
    fixed = re.sub(r",\s*([}\]])", r"\1", fixed)               # Komma vor Klammer
    try:
        return json.JSONDecoder().raw_decode(fixed)[0]
    except ValueError:
        pass
    try:
        from json_repair import repair_json
        data = repair_json(t, return_objects=True)
        return data if isinstance(data, (dict, list)) and data else None
    except Exception:  # noqa: BLE001
        return None


def ask_json(prompt, system=None, video_url=None, models=None, temperature=0.7, key=None):
    key = key or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY fehlt")
    parts = []
    if video_url:
        parts.append({"file_data": {"file_uri": video_url}})
    parts.append({"text": prompt})
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": temperature,
                                 "maxOutputTokens": 32768}}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    last, quota_hits = None, []
    models = models or DEFAULT_MODELS
    for m in models:
        r = None
        for attempt in range(3):
            r = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
                              headers={"x-goog-api-key": key}, json=body, timeout=300)
            if r.status_code in (500, 502, 503, 504):
                time.sleep(20 * (attempt + 1))
                continue
            break
        if r.status_code in (404, 400) and "not found" in r.text.lower():
            last = f"{m}: nicht verfügbar"
            continue
        if r.status_code in (500, 502, 503, 504):
            last = f"{m}: überlastet"
            continue
        if r.status_code == 429:                        # Limit gilt pro Modell -> nächstes probieren
            quota_hits.append(m)
            last = f"{m}: Gratis-Limit erreicht"
            continue
        r.raise_for_status()
        resp = r.json()
        cand = (resp.get("candidates") or [{}])[0]
        txt = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []) if not p.get("thought"))
        if not txt.strip():
            raise RuntimeError(f"{m}: leere Antwort ({cand.get('finishReason')}, {resp.get('promptFeedback')})")
        data = _parse_json(txt)
        if data is None:                               # kaputtes JSON (z. B. „…" in deutschem Text): nächstes Modell
            last = f"{m}: ungültiges JSON ({cand.get('finishReason')}); Anfang: {txt[:200]!r}"
            print(f"  ⚠ {last[:160]}")
            continue
        if isinstance(data, dict):
            data["_model"] = m
        return data
    if quota_hits and len(quota_hits) == len(models):
        raise QuotaError("Gemini-Gratis-Limit bei allen Modellen erreicht – morgen geht es weiter")
    raise RuntimeError(last or "kein Gemini-Modell verfügbar")


def research(question, models=None, key=None):
    """Faktenrecherche mit Google-Suche (Grounding). Gibt (Text, Quellen[(Titel, URL)]) zurück."""
    key = key or os.environ.get("GEMINI_API_KEY")
    body = {"contents": [{"parts": [{"text": question}]}], "tools": [{"google_search": {}}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 8192}}
    errs = []
    for m in models or DEFAULT_MODELS:
        r = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
                          headers={"x-goog-api-key": key}, json=body, timeout=300)
        if r.status_code != 200:
            errs.append(f"{m}: {r.status_code} {r.text[:160]}")
            continue
        cand = (r.json().get("candidates") or [{}])[0]
        txt = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []))
        chunks = (cand.get("groundingMetadata") or {}).get("groundingChunks", [])
        src = [(c["web"].get("title", ""), c["web"].get("uri", "")) for c in chunks if c.get("web")]
        return txt, src
    raise RuntimeError("Recherche fehlgeschlagen: " + " | ".join(errs))
