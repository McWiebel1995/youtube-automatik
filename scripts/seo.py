#!/usr/bin/env python3
"""
Suchoptimierung für LANGE Videos (YouTube): Stichwörter (Tags), Einstieg der Beschreibung, mehr Hashtags.

  meta = seo.enrich(meta, "regen")      # {"title","description","tags"} -> erweitert

- Tags: 20–30 echte Suchbegriffe (wie Leute suchen: "rain sounds for sleeping 3 hours"), max. 480 Zeichen
- Beschreibung: die ersten 1–2 Sätze enthalten die wichtigsten Suchbegriffe (YouTube zeigt ~150 Zeichen in der Suche)
- Hashtags: 3 wichtigste (stehen über dem Titel) + bis zu 5 weitere = max. 8 (ab 15 ignoriert YouTube alle)
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "anime"))

NICHE = {
    "regen": ("en", "relaxing rain sounds for sleep, study and relaxation (long ambience videos)"),
    "kamin": ("en", "cozy crackling fireplace ambience for sleep, reading and relaxation (long videos)"),
    "wasserfall": ("en", "waterfall, river and forest stream nature sounds for sleep, focus and meditation (long videos)"),
    "schlaf": ("de", "Spieluhr-Einschlafmusik für Babys und Kleinkinder (15 Minuten), Zielgruppe Eltern in Deutschland"),
    "geschichten": ("de", "Gute-Nacht-Geschichten zum Vorlesen/Hören für Kinder von 2–6 Jahren, Zielgruppe Eltern"),
    "whatif": ("en", "science 'what if' documentary videos (space, Earth, physics), audience: curious adults in the US"),
    "gedanken": ("de", "ruhige deutsche Gedanken/Impulse zum Entspannen und Einschlafen mit Naturbildern"),
    "lernen": ("en", "zodiac and astrology inspiration"),
}
TASK = """You are a YouTube SEO expert for this channel niche: {niche}.
Video title: {title}
Video description: {desc}
Language for all output: {lang_name}.
Give:
1. "keywords": {nkw} real search phrases people type into YouTube to find exactly this kind of video (mix of short
   head terms and long-tail phrases with duration/purpose, e.g. "rain sounds for sleeping", "3 hours rain no thunder").
   No channel names of competitors, no misleading terms.
2. "hashtags": {nhash} relevant hashtags (without #, no spaces, most important first).
3. "intro": {nintro} natural sentence(s) (max {nchars} characters) for the START of the description that contain the 2 most
   important search phrases. Friendly, not spammy.{kids}
Answer ONLY JSON: {{"keywords": ["..."], "hashtags": ["..."], "intro": "..."}}"""


def _fit_tags(tags, limit=480):
    out, used = [], 0
    for t in tags:
        t = re.sub(r"[<>,#\"]", "", t).strip()[:60]
        if not t or t.lower() in {x.lower() for x in out}:
            continue
        cost = len(t) + (2 if " " in t else 0) + (1 if out else 0)
        if used + cost > limit:
            continue
        out.append(t)
        used += cost
    return out


def enrich(meta, ch, core_hashtags=(), short=False):
    if ch not in NICHE:
        return meta
    lang, niche = NICHE[ch]
    import gemini
    kids = ("\n   This is a channel for parents of small children: no claims about health or medical sleep effects."
            if ch in ("schlaf", "geschichten") else "")
    js = gemini.ask_json(TASK.format(niche=niche, title=meta.get("title", ""), desc=meta.get("description", "")[:1500],
                                     lang_name="German" if lang == "de" else "English", kids=kids,
                                     nkw=15 if short else 25, nhash=5 if short else 8, nintro="1" if short else "1–2",
                                     nchars=120 if short else 200), temperature=0.4)
    kw = [k for k in js.get("keywords", []) if isinstance(k, str)]
    meta = dict(meta)
    meta["tags"] = _fit_tags(list(meta.get("tags") or []) + kw)
    intro = (js.get("intro") or "").strip()
    desc = meta.get("description", "")
    if intro and intro[:40].lower() not in desc.lower():
        desc = f"{intro}\n\n{desc}"
    hs = [h if h.startswith("#") else "#" + h for h in core_hashtags]
    for h in js.get("hashtags", []):
        h = "#" + re.sub(r"[^\wäöüÄÖÜß]", "", str(h).lstrip("#"))
        if len(h) > 2 and h.lower() not in {x.lower() for x in hs}:
            hs.append(h)
    if short and "#shorts" not in [h.lower() for h in hs]:
        hs.insert(min(2, len(hs)), "#shorts")
    hs = hs[:6 if short else 8]
    meta["description"] = f"{desc.strip()}\n\n{' '.join(hs)}"[:4900]
    meta["seo"] = {"keywords": len(meta["tags"]), "hashtags": len(hs)}
    return meta
