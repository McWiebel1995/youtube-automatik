#!/usr/bin/env python3
"""
KI 1 – VIRAL VIDEO HUNTER

Ablauf pro Lauf (siehe Master-Prompt, Abschnitt 12):
  1 DISCOVER   GDELT (weltweite Nachrichten-Ereignisse) + YouTube-Suche, mehrsprachig
  2 COLLECT    echte Metriken über die YouTube-API (nie erfunden)
  3 VERIFY     Gegenprüfung mit unabhängigen Nachrichtenquellen (GDELT)
  4 DEDUPLICATE gleiche Szene / Reuploads zu Ereignis-Clustern zusammenfassen
  5 ANALYZE    Gemini "schaut" das Video und bewertet es nach dem Master-Prompt
  6 SCORE      Anime-Score 0–100 (Social-Dynamik wird aus echten Zahlen berechnet)
  7 RANK       Sortierung; ungeprüfte bleiben gekennzeichnet
  8 EXPORT     anime/data/candidates.json fürs Dashboard + Übergabepakete

Umgebungsvariablen:
  YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN_HUNTER (oder ein anderes Kanal-Token)
  GEMINI_API_KEY (kostenlos: aistudio.google.com)

    python anime/hunter.py              # normaler Lauf
    python anime/hunter.py --no-ai      # ohne Gemini-Analyse
"""
import argparse
import datetime as dt
import json
import math
import os
import re
import sys
import time
from pathlib import Path

import requests
import yaml

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
DB_FILE = DATA / "db.json"
OUT_FILE = DATA / "candidates.json"
MASTER_PROMPT = (HERE / "prompts" / "hunter_master_prompt.md").read_text(encoding="utf-8")
UTC = dt.timezone.utc

NOT_ACCESSIBLE = [
    "TikTok: keine öffentliche Such-API für Privatnutzer – nicht durchsucht (Scraping verstößt gegen die Nutzungsbedingungen).",
    "Instagram Reels: keine Such-API für fremde Inhalte – nicht durchsucht.",
    "X / Twitter: Such-API kostenpflichtig – nicht durchsucht.",
    "Facebook Reels: keine Such-API für fremde Inhalte – nicht durchsucht.",
]


# ----------------------------------------------------------------- Hilfen
def now():
    return dt.datetime.now(UTC)


def iso(t):
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def parse_iso(s):
    if not s:
        return None
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def iso_duration_seconds(s):
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return None
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def tokens(text):
    return {w for w in re.findall(r"[a-zà-ÿäöüß0-9]{3,}", (text or "").lower())}


def load_db():
    if DB_FILE.exists():
        return json.loads(DB_FILE.read_text(encoding="utf-8"))
    return {"videos": {}, "decisions": [], "runs": []}


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


# ----------------------------------------------------------------- 1 DISCOVER: GDELT
def gdelt_articles(query, country, hours, notes):
    params = {"query": f"{query} sourcecountry:{country}" if country != "INT" else query,
              "mode": "artlist", "format": "json", "maxrecords": 200,
              "timespan": f"{hours}h", "sort": "hybridrel"}
    err = "zu viele Anfragen"
    for attempt in range(4):
        try:
            r = requests.get("https://api.gdeltproject.org/api/v2/doc/doc", params=params, timeout=40)
            if r.status_code == 429:
                time.sleep(20 * (attempt + 1))
                continue
            r.raise_for_status()
            arts = (r.json() or {}).get("articles", []) if r.text.strip().startswith("{") else []
            time.sleep(12)                     # GDELT: max. 1 Anfrage / 5 s – mit Sicherheitsabstand
            return arts
        except (requests.RequestException, ValueError) as e:
            err = e
            time.sleep(6)
    notes.append(f"GDELT {country}: nicht erreichbar ({err}).")
    return []


def city_counts(articles, cities):
    counts = {}
    for a in articles:
        t = a.get("title", "")
        for c in cities:
            if c.lower() in t.lower():
                counts[c] = counts.get(c, 0) + 1
    return sorted(counts.items(), key=lambda x: -x[1])


# ----------------------------------------------------------------- 1/2 DISCOVER + COLLECT: YouTube
def youtube():
    sys.path.insert(0, str(HERE.parent / "scripts"))
    import upload  # noqa: WPS433 – nutzt dieselbe Anmeldung wie die Upload-Pipeline
    for name in ["YT_REFRESH_TOKEN_HUNTER", "YT_REFRESH_TOKEN_KAMIN", "YT_REFRESH_TOKEN_REGEN",
                 "YT_REFRESH_TOKEN_WASSERFALL"]:
        if os.environ.get(name):
            return upload.service(os.environ[name])
    raise SystemExit("Kein YouTube-Token gefunden (YT_REFRESH_TOKEN_HUNTER).")


def yt_search(yt, q, lang, since):
    res = yt.search().list(part="id", q=q, type="video", maxResults=25, order="viewCount",
                           publishedAfter=iso(since), relevanceLanguage=lang).execute()
    return [i["id"]["videoId"] for i in res.get("items", []) if i.get("id", {}).get("videoId")]


def yt_details(yt, ids):
    out = []
    for i in range(0, len(ids), 50):
        res = yt.videos().list(part="snippet,statistics,contentDetails",
                               id=",".join(ids[i:i + 50])).execute()
        out += res.get("items", [])
    return out


def num(x):
    return int(x) if x is not None and str(x).isdigit() else None


# ----------------------------------------------------------------- 6 SCORE (Social-Teil)
def social_score(v):
    vel, er = v.get("views_velocity_per_hour"), v.get("engagement_rate")
    if vel is None and er is None:
        return 0
    s = 0
    if vel is not None:
        s += next((p for lim, p in [(50000, 10), (10000, 8), (2000, 6), (500, 4), (100, 2)] if vel >= lim), 1)
    if er is not None:
        s += next((p for lim, p in [(8, 5), (4, 4), (2, 3), (1, 2)] if er >= lim), 1)
    return min(15, s)


def update_metrics(v, stats, t):
    views, likes, comments = num(stats.get("viewCount")), num(stats.get("likeCount")), num(stats.get("commentCount"))
    snaps = v.setdefault("snapshots", [])
    if not snaps or snaps[-1]["views"] != views:
        snaps.append({"t": iso(t), "views": views, "likes": likes, "comments": comments})
    v.update(views=views, likes=likes, comments=comments, shares=None)   # Shares liefert YouTube nicht
    if views:
        v["engagement_rate"] = round(((likes or 0) + (comments or 0)) / views * 100, 2) \
            if likes is not None or comments is not None else None
    # Views Velocity: aus zwei Messpunkten (gemessen) oder seit Veröffentlichung (geschätzt)
    vel, kind = None, None
    if len(snaps) >= 2:
        a, b = snaps[-2], snaps[-1]
        hrs = (parse_iso(b["t"]) - parse_iso(a["t"])).total_seconds() / 3600
        if hrs >= 0.5 and a["views"] is not None and b["views"] is not None:
            vel, kind = (b["views"] - a["views"]) / hrs, "gemessen (zwei Messpunkte)"
    if vel is None and views is not None and v.get("published_at"):
        hrs = max(1.0, (t - parse_iso(v["published_at"])).total_seconds() / 3600)
        vel, kind = views / hrs, "Durchschnitt seit Veröffentlichung"
    v["views_velocity_per_hour"] = round(vel) if vel is not None else None
    v["velocity_basis"] = kind


# ----------------------------------------------------------------- 3 VERIFY
def verify(v, region_articles):
    city = v.get("city")
    if not city:
        return
    pub = parse_iso(v.get("published_at"))
    hits = {}
    for a in region_articles.get(v["region"], []) + region_articles.get("INT", []):
        if city.lower() not in a.get("title", "").lower():
            continue
        seen = a.get("seendate")
        try:
            st = dt.datetime.strptime(seen, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC) if seen else None
        except ValueError:
            st = None
        if pub and st and abs((st - pub).total_seconds()) > 48 * 3600:
            continue
        dom = a.get("domain")
        if dom and dom not in hits:
            hits[dom] = {"domain": dom, "title": a.get("title"), "url": a.get("url"), "seen": seen}
    v["verification_sources"] = list(hits.values())[:6]
    if v.get("authenticity_status") in ("VERIFIED", "SYNTHETIC", "MISLEADING"):
        return                                         # manuelle / KI-Einstufung nicht überschreiben
    v["authenticity_status"] = "PARTIALLY_VERIFIED" if len(hits) >= 2 else "UNVERIFIED"
    v["verification_note"] = (f"Ereignis in {city} durch {len(hits)} unabhängige Nachrichtenquellen belegt; "
                              "dass genau dieses Video das Ereignis zeigt, ist NICHT geprüft – manuelle Prüfung nötig."
                              if len(hits) >= 2 else
                              "Keine unabhängigen Nachrichtenquellen zum Ereignis gefunden.")


# ----------------------------------------------------------------- 4 DEDUPLICATE
def cluster(videos):
    items = sorted(videos.values(), key=lambda v: v.get("published_at") or "")
    for v in items:
        v["cluster"] = v["video_id"]
    for i, a in enumerate(items):
        ta = tokens(a.get("title"))
        for b in items[:i]:
            if a.get("city") != b.get("city") or not a.get("city"):
                continue
            ta2, tb = ta, tokens(b.get("title"))
            jac = len(ta2 & tb) / max(1, len(ta2 | tb))
            dtime = abs((parse_iso(a["published_at"]) - parse_iso(b["published_at"])).total_seconds())
            if jac >= 0.5 and dtime < 36 * 3600:
                a["cluster"] = b["cluster"]
                break


# ----------------------------------------------------------------- 5 ANALYZE: Gemini
ANALYSIS_TASK = """
Analysiere das angehängte YouTube-Video gemäß den Abschnitten 5, 7, 8 und 9 des Master-Prompts.

Bekannte, gemessene Fakten (nicht verändern, nicht ergänzen):
{facts}

Wichtige Rahmenbedingungen dieses Projekts:
- Das Originalvideo wird NICHT verwendet. Es dient nur als Inspiration für eine FIKTIVE Anime-Geschichte
  mit frei erfundenen Figuren. Keine echte Person darf erkennbar nachgebildet werden.
- Die Anime-Shorts werden auf ENGLISCH produziert. Schreibe "anime_concept", "fictional_character"
  und "anime_imagery" daher auf Englisch, alles andere auf Deutsch.
- Keine politische Position bevorzugen oder benachteiligen; erzähle die menschliche Seite.
- "Gemessene Social-Media-Dynamik" bewertest du NICHT – die wird aus echten Zahlen berechnet.

Antworte ausschließlich mit JSON nach diesem Schema:
{{
 "relevant": true/false,                       // zeigt das Video überhaupt ein reales Ereignis?
 "event_description": "was sichtbar passiert, nur Beobachtungen",
 "city_guess": "Stadt oder null", "country_guess": "Land oder null",
 "emotional_observations": ["sichtbare/hörbare Emotionen, keine unbelegten Gedanken"],
 "visual_highlights": [{{"timecode": "mm:ss", "beschreibung": "..."}}],
 "story_potential": "Einstieg → Konflikt → Wendepunkt → Höhepunkt → Nachhall (fiktional)",
 "anime_concept": "short English concept, clearly fictional",
 "fictional_character": "invented protagonist (English)",
 "recommended_perspective": "Erzählperspektive",
 "anime_imagery": "visual style (English)",
 "sound_ideas": ["..."],
 "recommended_length_seconds": 30-60,
 "scores": {{"emotional": 0-20, "transformation": 0-20, "cinematic": 0-15,
             "story": 0-15, "originality": 0-10, "technical": 0-5}},
 "synthetic_suspected": true/false, "misleading_suspected": true/false,
 "authenticity_concerns": ["..."],
 "open_questions": ["was unbestätigt bleibt"],
 "sensitive_content": ["z. B. Gewalt, Verletzte, Minderjährige erkennbar"]
}}
"""

SCORE_MAX = {"emotional": 20, "transformation": 20, "cinematic": 15, "story": 15, "originality": 10, "technical": 5}


def gemini_analyze(v, models, key, context_titles):
    facts = json.dumps({k: v.get(k) for k in ["title", "creator", "published_at", "views", "likes", "comments",
                                              "engagement_rate", "views_velocity_per_hour", "language",
                                              "duration_seconds"]}, ensure_ascii=False)
    if context_titles:
        facts += "\nNachrichten-Schlagzeilen zur gleichen Zeit/Region (GDELT):\n- " + "\n- ".join(context_titles[:8])
    body = {
        "systemInstruction": {"parts": [{"text": MASTER_PROMPT}]},
        "contents": [{"parts": [{"file_data": {"file_uri": v["video_url"]}},
                                {"text": ANALYSIS_TASK.format(facts=facts)}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.3},
    }
    last = None
    for m in models:
        for attempt in range(3):
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
                              headers={"x-goog-api-key": key}, json=body, timeout=240)
            if r.status_code in (500, 502, 503, 504):        # überlastet -> kurz warten, nochmal
                time.sleep(20 * (attempt + 1))
                continue
            break
        if r.status_code in (404, 400) and "not found" in r.text.lower():
            last = f"{m}: nicht verfügbar"
            continue
        if r.status_code in (500, 502, 503, 504):
            last = f"{m}: überlastet ({r.status_code})"
            continue
        if r.status_code == 429:
            raise RuntimeError("Gemini-Gratis-Limit erreicht")
        if r.status_code == 403:
            raise PermissionError("Video für die KI-Analyse gesperrt (z. B. Altersbeschränkung/Region)")
        r.raise_for_status()
        txt = "".join(p.get("text", "") for p in r.json()["candidates"][0]["content"]["parts"])
        data = json.loads(txt[txt.index("{"): txt.rindex("}") + 1])
        data["_model"] = m
        return data
    raise TimeoutError(last or "kein Gemini-Modell verfügbar")


def apply_analysis(v, a):
    v["analysis"] = a
    v["analyzed_at"] = iso(now())
    for k in ["event_description", "emotional_observations", "visual_highlights", "story_potential",
              "anime_concept", "fictional_character", "recommended_perspective", "anime_imagery",
              "sound_ideas", "recommended_length_seconds", "authenticity_concerns", "open_questions",
              "sensitive_content"]:
        if a.get(k) is not None:
            v[k] = a[k]
    if not v.get("city") and a.get("city_guess"):
        v["city"], v["city_source"] = a["city_guess"], "KI-Schätzung"
    if not v.get("country") and a.get("country_guess"):
        v["country"] = a["country_guess"]
    if a.get("synthetic_suspected"):
        v["authenticity_status"] = "SYNTHETIC"
    elif a.get("misleading_suspected"):
        v["authenticity_status"] = "MISLEADING"
    if a.get("relevant") is False:
        v["irrelevant"] = True


def total_score(v):
    sc = (v.get("analysis") or {}).get("scores")
    soc = social_score(v)
    v["score_breakdown"] = {"social": soc}
    if not sc:
        v["anime_score"] = None
        return
    s = soc
    for k, mx in SCORE_MAX.items():
        val = max(0, min(mx, float(sc.get(k, 0) or 0)))
        v["score_breakdown"][k] = val
        s += val
    v["anime_score"] = round(s)


# ----------------------------------------------------------------- Hauptablauf
def run(no_ai=False):
    cfg = yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))
    db = load_db()
    t = now()
    since = t - dt.timedelta(hours=cfg["window_hours"])
    notes = list(NOT_ACCESSIBLE)
    stats_run = {"started": iso(t), "queries": [], "new": 0, "analyzed": 0}

    # 1 DISCOVER – GDELT
    region_articles, signals = {}, {}
    for code, r in cfg["regions"].items():
        arts = gdelt_articles(r["gdelt"], code, cfg["window_hours"], notes)
        region_articles[code] = arts
        signals[code] = city_counts(arts, r["cities"])
        print(f"GDELT {code}: {len(arts)} Artikel, Hotspots: {signals[code][:3]}")

    # Suchbegriffe: Regionen mit mehr Nachrichten bekommen mehr Suchen
    queries = []
    order = sorted(cfg["regions"], key=lambda c: -len(region_articles.get(c, [])))
    for code in order:
        r = cfg["regions"][code]
        hot = [c for c, _ in signals[code][:2]] or r["cities"][:1]
        for tpl in r["youtube"]:
            if "{city}" in tpl:
                queries += [(tpl.format(city=c), r["lang"], code, c) for c in hot]
            else:
                queries.append((tpl, r["lang"], code, None))
    # reihum über Regionen verteilen, dann auf Budget kürzen
    by_region = {}
    for q in queries:
        by_region.setdefault(q[2], []).append(q)
    mixed = []
    while any(by_region.values()):
        for code in order:
            if by_region.get(code):
                mixed.append(by_region[code].pop(0))
    queries = mixed[: cfg["max_youtube_queries"]]

    # 1/2 DISCOVER + COLLECT – YouTube
    yt = youtube()
    found = {}
    for q, lang, code, city in queries:
        try:
            ids = yt_search(yt, q, lang, since)
        except Exception as e:  # noqa: BLE001
            notes.append(f"YouTube-Suche '{q}': {e}")
            continue
        stats_run["queries"].append({"q": q, "results": len(ids)})
        for i in ids:
            found.setdefault(i, (code, city, q))
    ids = list(set(found) | {k for k, v in db["videos"].items() if not v.get("decision")
                            and parse_iso(v["published_at"]) > since})
    details = yt_details(yt, ids) if ids else []
    excl = [w.lower() for w in cfg["exclude_words"]]

    for it in details:
        vid, sn, st, cd = it["id"], it["snippet"], it.get("statistics", {}), it.get("contentDetails", {})
        text = f"{sn.get('title', '')} {sn.get('description', '')}".lower()
        v = db["videos"].get(vid)
        if v is None:
            if any(w in text for w in excl):
                continue
            if num(st.get("viewCount")) is not None and num(st.get("viewCount")) < cfg["min_views"]:
                continue
            dur = iso_duration_seconds(cd.get("duration")) or 0
            if sn.get("liveBroadcastContent", "none") != "none" or dur == 0 or dur > cfg["max_listing_minutes"] * 60:
                continue                                    # Livestreams / lange Nachrichtensendungen
            code, query_city, q = found.get(vid, ("INT", None, None))
            # Stadt nur übernehmen, wenn sie im Titel/Text steht – der Suchbegriff allein ist kein Beleg
            city = next((c for r in cfg["regions"].values() for c in r["cities"] if c.lower() in text), None)
            v = {
                "video_id": vid, "platform": "YouTube",
                "video_url": f"https://www.youtube.com/watch?v={vid}",
                "thumbnail": (sn.get("thumbnails", {}).get("high") or sn.get("thumbnails", {}).get("default") or {}).get("url"),
                "creator": sn.get("channelTitle"), "title": sn.get("title"),
                "country": {"FR": "Frankreich", "IT": "Italien", "GM": "Deutschland", "SP": "Spanien"}.get(code),
                "region": code, "city": city, "city_source": "Titel/Beschreibung" if city else None,
                "found_by_query": q,
                "event_description": None, "event_date": None,
                "published_at": sn.get("publishedAt"), "collected_at": iso(t),
                "language": sn.get("defaultAudioLanguage") or sn.get("defaultLanguage") or cfg["regions"][code]["lang"],
                "duration_seconds": iso_duration_seconds(cd.get("duration")),
                "authenticity_status": "UNVERIFIED", "verification_sources": [],
                "rights_status": "NOT_CLEARED – Originalmaterial wird nicht verwendet, nur Inspiration",
                "manual_review_required": True,
            }
            db["videos"][vid] = v
            stats_run["new"] += 1
        update_metrics(v, st, t)

    # 3 VERIFY + 4 DEDUPLICATE
    for v in db["videos"].values():
        verify(v, region_articles)
    cluster(db["videos"])

    # 5 ANALYZE – die vielversprechendsten noch nicht analysierten Videos
    key = os.environ.get("GEMINI_API_KEY")
    if not no_ai and key:
        queue = [v for v in db["videos"].values()
                 if not v.get("analysis") and not v.get("analysis_failed")
                 and (v.get("duration_seconds") or 0) <= cfg["max_video_minutes"] * 60
                 and v["cluster"] == v["video_id"]]
        queue.sort(key=lambda v: (-social_score(v), -(v.get("views") or 0)))
        for v in queue[: cfg["max_analyses_per_run"]]:
            ctx = [a.get("title", "") for a in region_articles.get(v["region"], [])
                   if v.get("city") and v["city"].lower() in a.get("title", "").lower()]
            try:
                apply_analysis(v, gemini_analyze(v, cfg["gemini_models"], key, ctx))
                stats_run["analyzed"] += 1
                print(f"  ✓ analysiert: {v['title'][:70]}")
            except RuntimeError as e:                 # Tageslimit -> nächster Lauf
                notes.append(f"Gemini: {e}")
                print(f"  ⚠ {e}")
                break
            except TimeoutError as e:                 # vorübergehend -> beim nächsten Lauf erneut
                v["analysis_tries"] = v.get("analysis_tries", 0) + 1
                if v["analysis_tries"] >= 3:
                    v["analysis_failed"] = str(e)[:200]
                print(f"  ⚠ später erneut ({v['video_id']}): {e}")
            except Exception as e:  # noqa: BLE001
                v["analysis_failed"] = str(e)[:200]
                print(f"  ⚠ Analyse fehlgeschlagen ({v['video_id']}): {e}")
            time.sleep(7)                     # Gratis-Limit: wenige Anfragen pro Minute
    elif not key:
        notes.append("GEMINI_API_KEY fehlt – Videos wurden nicht per KI analysiert (kein Anime-Score).")

    # 6 SCORE
    for v in db["videos"].values():
        total_score(v)

    # Aufräumen
    cutoff = t - dt.timedelta(days=cfg["keep_days"])
    db["videos"] = {k: v for k, v in db["videos"].items()
                    if v.get("decision") == "approved" or parse_iso(v["collected_at"]) > cutoff}

    stats_run["finished"] = iso(now())
    db["runs"] = (db.get("runs") or [])[-50:] + [stats_run]
    save_json(DB_FILE, db)
    export(db, cfg, notes, signals)
    print(f"Fertig: {stats_run['new']} neue Videos, {stats_run['analyzed']} analysiert.")


# ----------------------------------------------------------------- 7 RANK + 8 EXPORT
PUBLIC_FIELDS = ["video_id", "platform", "video_url", "thumbnail", "creator", "title", "country", "city",
                 "event_description", "event_date", "published_at", "collected_at", "language", "duration_seconds",
                 "views", "likes", "comments", "shares", "engagement_rate", "views_velocity_per_hour",
                 "velocity_basis", "emotional_observations", "visual_highlights", "story_potential",
                 "anime_concept", "fictional_character", "recommended_perspective", "anime_imagery",
                 "sound_ideas", "recommended_length_seconds", "anime_score", "score_breakdown",
                 "authenticity_status", "verification_note", "verification_sources", "authenticity_concerns",
                 "open_questions", "sensitive_content", "rights_status", "manual_review_required",
                 "decision", "decided_at", "cluster", "snapshots"]


def export(db, cfg, notes, signals):
    vids = [v for v in db["videos"].values() if not v.get("irrelevant")]
    clusters = {}
    for v in vids:
        clusters.setdefault(v["cluster"], []).append(v)
    mains = []
    for members in clusters.values():
        members.sort(key=lambda v: -(v.get("views") or 0))
        m = dict(members[0])
        if m.get("anime_score") is None:                     # Score vom analysierten Mitglied übernehmen
            for o in members:
                if o.get("anime_score") is not None:
                    m.update({k: o.get(k) for k in PUBLIC_FIELDS if k.startswith(("anime", "story", "emotional",
                              "visual", "fictional", "recommended", "sound", "score", "event_description"))})
                    break
        m["duplicates"] = [{"video_url": o["video_url"], "creator": o.get("creator"), "views": o.get("views")}
                           for o in members[1:]]
        mains.append(m)

    def rank(v):
        unverified = v.get("authenticity_status") in ("UNVERIFIED", "SYNTHETIC", "MISLEADING")
        return (v.get("decision") == "rejected", v.get("anime_score") is None, unverified,
                -(v.get("anime_score") or 0), -(v.get("views_velocity_per_hour") or 0))
    mains.sort(key=rank)
    out = {
        "updated_at": iso(now()),
        "stats": {
            "found": len(vids),
            "clusters": len(mains),
            "verified": sum(v.get("authenticity_status") in ("VERIFIED", "PARTIALLY_VERIFIED") for v in mains),
            "top": sum((v.get("anime_score") or 0) >= cfg["top_threshold"] for v in mains),
            "approved": sum(v.get("decision") == "approved" for v in mains),
        },
        "hotspots": {k: v[:5] for k, v in signals.items()},
        "access_notes": notes,
        "last_runs": db.get("runs", [])[-5:],
        "candidates": [{k: v.get(k) for k in PUBLIC_FIELDS + ["duplicates"]} for v in mains[:150]],
    }
    save_json(OUT_FILE, out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-ai", action="store_true")
    run(ap.parse_args().no_ai)
