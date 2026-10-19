"""Kleiner Gemini-Client (REST) mit Modell-Fallback und Wiederholung bei Überlastung."""
import json
import os
import time

import requests

DEFAULT_MODELS = ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash"]


class QuotaError(RuntimeError):
    """Gratis-Limit erreicht – später erneut."""


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
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
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
        try:
            data = json.loads(txt[txt.index("{"): txt.rindex("}") + 1])
        except ValueError as e:
            raise RuntimeError(f"{m}: ungültiges JSON ({cand.get('finishReason')}): {e}; Anfang: {txt[:200]!r}") from e
        data["_model"] = m
        return data
    if quota_hits and len(quota_hits) == len(models):
        raise QuotaError("Gemini-Gratis-Limit bei allen Modellen erreicht – morgen geht es weiter")
    raise RuntimeError(last or "kein Gemini-Modell verfügbar")
