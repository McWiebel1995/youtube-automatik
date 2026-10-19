#!/usr/bin/env python3
"""
Freigabe / Ablehnung eines Kandidaten (wird vom Workflow "Anime – Freigabe" aufgerufen).

    python anime/review.py approve VIDEO_ID [--note "..."]
    python anime/review.py reject  VIDEO_ID [--note "..."]

Bei Freigabe entsteht das Übergabepaket für KI 2 (Abschnitt 13 des Master-Prompts):
    anime/data/handoff/VIDEO_ID.json
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["approve", "reject"])
    ap.add_argument("video_id")
    ap.add_argument("--note", default="")
    a = ap.parse_args()

    db = json.loads((DATA / "db.json").read_text(encoding="utf-8"))
    v = db["videos"].get(a.video_id)
    if not v:
        sys.exit(f"Kandidat {a.video_id} nicht gefunden.")
    t = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    v["decision"] = "approved" if a.action == "approve" else "rejected"
    v["decided_at"] = t
    db.setdefault("decisions", []).append({"video_id": a.video_id, "decision": v["decision"], "at": t,
                                           "score": v.get("anime_score"), "note": a.note})

    if a.action == "approve":
        pkg = {
            "_hinweis": "Reale Fakten (real_*) und künstlerische Vorschläge (creative_*) sind strikt getrennt. "
                        "Das Originalvideo wird nicht verwendet; alle Figuren sind fiktiv.",
            "video_id": a.video_id,
            "real_original_video_url": v.get("video_url"),
            "real_platform": v.get("platform"),
            "real_event_description": v.get("event_description"),
            "real_location": {"city": v.get("city"), "country": v.get("country")},
            "real_published_at": v.get("published_at"),
            "real_sources": v.get("verification_sources"),
            "real_open_questions": v.get("open_questions"),
            "real_visual_highlights": v.get("visual_highlights"),
            "real_emotional_observations": v.get("emotional_observations"),
            "real_sensitive_content": v.get("sensitive_content"),
            "creative_anime_concept": v.get("anime_concept"),
            "creative_fictional_character": v.get("fictional_character"),
            "creative_perspective": v.get("recommended_perspective"),
            "creative_imagery": v.get("anime_imagery"),
            "creative_sound_ideas": v.get("sound_ideas"),
            "creative_story_arc": v.get("story_potential"),
            "recommended_length_seconds": v.get("recommended_length_seconds"),
            "anime_score": v.get("anime_score"),
            "authenticity_status": v.get("authenticity_status"),
            "rights_status": v.get("rights_status"),
            "approval_note": a.note,
            "approved_at": t,
            "language": "en",
        }
        (DATA / "handoff").mkdir(parents=True, exist_ok=True)
        (DATA / "handoff" / f"{a.video_id}.json").write_text(json.dumps(pkg, ensure_ascii=False, indent=1),
                                                            encoding="utf-8")

    (DATA / "db.json").write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")
    cand = DATA / "candidates.json"
    if cand.exists():
        c = json.loads(cand.read_text(encoding="utf-8"))
        for x in c.get("candidates", []):
            if x["video_id"] == a.video_id or x.get("cluster") == v.get("cluster"):
                x["decision"], x["decided_at"] = v["decision"], t
        c["stats"]["approved"] = sum(x.get("decision") == "approved" for x in c["candidates"])
        cand.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{a.video_id}: {v['decision']}")


if __name__ == "__main__":
    main()
