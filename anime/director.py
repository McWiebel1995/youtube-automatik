#!/usr/bin/env python3
"""
KI 2 – ANIME STORY DIRECTOR

Macht aus einem freigegebenen Kandidaten (anime/data/handoff/ID.json) ein englisches
Drehbuch + Storyboard für einen 30–60-Sekunden-Short und prüft die Figuren auf zu große
Ähnlichkeit mit echten Personen (Recht am eigenen Bild).

    python anime/director.py              # alle freigegebenen ohne Drehbuch
    python anime/director.py --id VIDEOID # nur einen
    python anime/director.py --id VIDEOID --force   # neu schreiben

Ergebnis: anime/data/scripts/ID.json  und  anime/data/scripts.json (Übersicht fürs Dashboard)
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gemini  # noqa: E402

DATA = HERE / "data"
HANDOFF = DATA / "handoff"
SCRIPTS = DATA / "scripts"
SYSTEM = (HERE / "prompts" / "director_master_prompt.md").read_text(encoding="utf-8")
END_CARD = "Fictional story inspired by real events."

SCRIPT_TASK = """
Hier ist das Übergabepaket von KI 1 (JSON). Das Originalvideo ist angehängt, damit du Ablauf,
Choreografie und Stimmung authentisch übernehmen kannst – aber halte dich strikt an die Regeln
zu fiktiven Figuren.

{handoff}

{revision}

Schreibe das komplette Drehbuch + Storyboard. Alle Texte, die im Video vorkommen (Dialog,
Voice-over, Titel, Prompts, YouTube-Texte), auf ENGLISCH. Felder mit "_de" auf Deutsch.
Antworte ausschließlich mit JSON nach diesem Schema:
{{
 "title": "short punchy English title",
 "logline": "one sentence (English)",
 "logline_de": "ein Satz auf Deutsch",
 "total_duration_s": 30-60,
 "setting": {{"location": "fictional or generic place", "time": "...", "weather": "...",
             "color_palette": "...", "art_style": "high-end cinematic anime, ..."}},
 "characters": [{{
    "id": "c1", "name": "fictional name", "role": "...", "age_group": "...", "build": "...",
    "design_sheet": "precise, reusable visual description for image prompts (face, hair, eyes, clothes, colors)",
    "inspired_by_scene_de": ["was bewusst ähnlich ist (Rolle, Körpersprache, Kleidungstyp, max. 2 Merkmale wie Brille/Bart in anderer Ausführung)"],
    "changed_de": ["was bewusst anders ist (Gesicht, Frisur, Haarfarbe, Logos, Name …)"],
    "voice": "voice description (English)"
 }}],
 "shots": [{{
    "n": 1, "duration_s": 3-5, "beat": "HOOK|EINSTIEG|KONFLIKT|WENDEPUNKT|HÖHEPUNKT|NACHHALL",
    "camera": "shot size + angle + movement",
    "action": "what happens (English)",
    "dialogue": [{{"character": "c1", "line": "..."}}],
    "voiceover": "inner monologue or null",
    "sfx": ["..."], "music": "music cue for this shot",
    "on_screen_text": null,
    "image_prompt": "full prompt for the key frame, repeat character design_sheet, art style, lighting, 9:16",
    "motion_prompt": "how the key frame animates (camera + character motion, impact frames, speed lines)"
 }}],
 "music": {{"mood": "...", "bpm": 60-140, "instruments": ["..."]}},
 "end_card": "{end_card}",
 "content_check_de": {{"gewalt": "wie dargestellt", "kein_gore": true, "politisch_neutral": true}},
 "youtube": {{"title": "max 90 chars incl. #shorts", "description": "English, ends with the end card sentence",
             "tags": ["..."]}}
}}
"""

AUDIT_TASK = """
Du bist ein strenger Prüfer für das Recht am eigenen Bild (deutsches KUG / DSGVO).
Vergleiche die realen Personen im angehängten Video mit diesen fiktiven Anime-Figuren:

{characters}

Regeln: Ähnlich sein dürfen Rolle, Altersgruppe, Statur, Körpersprache, Kleidungstyp, Stimmung und
höchstens zwei markante Merkmale (z. B. Brille, Bart) in ANDERER Ausführung. Gesicht, Frisur+Haarfarbe,
Tattoos, Logos, Namen, Marken und Orte müssen anders sein. Maßstab: Könnten Bekannte die reale
Person in der Figur eindeutig wiedererkennen?

Antworte nur mit JSON:
{{"characters": [{{"id": "c1", "matching_features": ["..."], "risk": "low|medium|high",
   "required_changes": ["konkrete Änderung, falls nötig"]}}],
  "brands_or_text_visible_in_script": ["reale Marken/Schilder, die im Drehbuch vorkommen"],
  "overall_risk": "low|medium|high"}}
"""

GORE_WORDS = ["gore", "dismember", "decapitat", "blood spray", "spurting blood", "pool of blood",
              "exposed bone", "guts", "intestines", "severed"]


def now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def static_checks(script):
    """Einfache, nicht-KI-Prüfungen: Gore-Wörter, Endtafel, Länge, Pflichtfelder."""
    issues = []
    checked = {k: script.get(k) for k in ("shots", "characters", "setting", "youtube", "title", "logline")}
    text = json.dumps(checked, ensure_ascii=False).lower()       # content_check_de enthält "kein_gore"
    for w in GORE_WORDS:
        if w in text:
            issues.append(f"Gore-Begriff im Drehbuch: „{w}“")
    shots = script.get("shots") or []
    if not 5 <= len(shots) <= 12:
        issues.append(f"{len(shots)} Shots (erwartet 6–10)")
    total = sum(float(s.get("duration_s") or 0) for s in shots)
    if not 25 <= total <= 65:
        issues.append(f"Gesamtlänge {total:.0f} s (erwartet 30–60 s)")
    for s in shots:
        if not s.get("image_prompt") or not s.get("motion_prompt"):
            issues.append(f"Shot {s.get('n')}: Bild- oder Bewegungs-Prompt fehlt")
    script["end_card"] = END_CARD
    desc = (script.get("youtube") or {}).get("description", "")
    if END_CARD.lower() not in desc.lower():
        script.setdefault("youtube", {})["description"] = (desc.rstrip() + "\n\n" + END_CARD).strip()
    return issues


def direct(vid, force=False):
    hf = HANDOFF / f"{vid}.json"
    out = SCRIPTS / f"{vid}.json"
    if out.exists() and not force:
        return json.loads(out.read_text(encoding="utf-8"))
    handoff = json.loads(hf.read_text(encoding="utf-8"))
    url = handoff.get("real_original_video_url")
    print(f"▶ KI 2: {vid}")

    revision, audit, script = "", None, None
    for round_ in range(2):                       # Drehbuch + max. 1 Überarbeitung der Figuren
        script = gemini.ask_json(
            SCRIPT_TASK.format(handoff=json.dumps(handoff, ensure_ascii=False, indent=1),
                               revision=revision, end_card=END_CARD),
            system=SYSTEM, video_url=url, temperature=0.8)
        audit = gemini.ask_json(
            AUDIT_TASK.format(characters=json.dumps(script.get("characters", []), ensure_ascii=False, indent=1)),
            video_url=url, temperature=0.1)
        if audit.get("overall_risk") != "high":
            break
        changes = [c for ch in audit.get("characters", []) for c in ch.get("required_changes", [])]
        revision = ("ÜBERARBEITUNG NÖTIG – die Figuren sind realen Personen zu ähnlich. "
                    "Setze diese Änderungen um und behalte die Geschichte bei:\n- " + "\n- ".join(changes))
        print("  ↻ Figuren zu ähnlich – überarbeite …")

    issues = static_checks(script)
    record = {
        "video_id": vid, "created_at": now(), "status": "draft",
        "source": {"video_url": url, "event": handoff.get("real_event_description"),
                   "location": handoff.get("real_location"), "anime_score": handoff.get("anime_score"),
                   "authenticity_status": handoff.get("authenticity_status")},
        "script": script, "likeness_audit": audit, "issues": issues,
        "model": script.get("_model"),
    }
    SCRIPTS.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  ✓ „{script.get('title')}“ – {len(script.get('shots', []))} Shots, "
          f"Ähnlichkeits-Risiko: {(audit or {}).get('overall_risk')}, Hinweise: {len(issues)}")
    return record


def build_index():
    items = []
    for f in sorted(SCRIPTS.glob("*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        s = r.get("script", {})
        items.append({
            "video_id": r["video_id"], "created_at": r.get("created_at"), "status": r.get("status"),
            "decided_at": r.get("decided_at"), "title": s.get("title"), "logline": s.get("logline"),
            "logline_de": s.get("logline_de"), "duration": s.get("total_duration_s"),
            "setting": s.get("setting"), "characters": s.get("characters"), "shots": s.get("shots"),
            "music": s.get("music"), "youtube": s.get("youtube"), "end_card": s.get("end_card"),
            "likeness": r.get("likeness_audit"), "issues": r.get("issues"), "source": r.get("source"),
        })
    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    (DATA / "scripts.json").write_text(json.dumps({"updated_at": now(), "scripts": items},
                                                  ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--id")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    ids = [a.id] if a.id else [p.stem for p in sorted(HANDOFF.glob("*.json"))]
    errors = {}
    print(f"KI 2: {len(ids)} Übergabepaket(e): {ids}")
    for vid in ids:
        if not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", vid) or not (HANDOFF / f"{vid}.json").exists():
            print(f"  ⚠ kein Übergabepaket für {vid}")
            continue
        try:
            direct(vid, force=a.force)
        except gemini.QuotaError as e:
            print(f"  ⚠ {e} – nächster Versuch beim nächsten Lauf")
            errors[vid] = {"at": now(), "error": f"Gemini-Limit: {e}"}
            break
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ {vid}: {e}")
            errors[vid] = {"at": now(), "error": str(e)[:600]}
    (DATA / "director_errors.json").write_text(json.dumps(errors, ensure_ascii=False, indent=1), encoding="utf-8")
    build_index()


if __name__ == "__main__":
    main()
