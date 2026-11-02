#!/usr/bin/env python3
"""Welche Quiz-Themen laufen am besten? Aus data/analytics/report.json + data/quiz_log.json -> data/quiz_themes.json

Wertung je Quiz: Aufrufe x (angesehener Anteil / 50 %), nur Quiz älter als 2 Tage. Je Thema der Mittelwert,
normiert auf das beste Thema = 1.0. Ältere Quiz ohne Protokoll werden über Stichworte im Titel zugeordnet.
"""
import datetime as dt
import json
import re
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
GUESS = [(r"earth|ocean", "oceans and sea life"), (r"space|planet", "space and planets"), (r"dino", "dinosaurs"),
         (r"animal", "animals"), (r"invent", "inventions"), (r"moon", "the Moon"), (r"black hole|star", "black holes and stars"),
         (r"body|human", "the human body"), (r"brain", "the brain"), (r"weather|climate", "weather and climate"),
         (r"physic", "physics in everyday life")]


def main():
    rep = json.loads((ROOT / "data/analytics/report.json").read_text())
    log = {x["id"]: x["theme"] for x in json.loads((ROOT / "data/quiz_log.json").read_text())} \
        if (ROOT / "data/quiz_log.json").exists() else {}
    ch = next(c for c in rep["youtube"] if c.get("key") == "whatif")
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)).isoformat()
    per = {}
    for v in ch.get("videos", []):
        if "quiz" not in v["title"].lower() or v["published"] > cutoff[:19]:
            continue
        theme = log.get(v["id"]) or next((t for pat, t in GUESS if re.search(pat, v["title"].lower())), None)
        if not theme:
            continue
        score = v.get("a_views", v["views"]) * (v.get("averageViewPercentage", 50) / 50)
        per.setdefault(theme, []).append(score)
    best = max([st.mean(x) for x in per.values()] or [1]) or 1
    out = {t: {"n": len(x), "score": round(st.mean(x) / best, 3)} for t, x in per.items()}
    (ROOT / "data/quiz_themes.json").write_text(json.dumps(dict(sorted(out.items(), key=lambda kv: -kv[1]["score"])),
                                                           indent=1), encoding="utf-8")
    lines = [f"{t}: {o['score']:.2f} ({o['n']} Quiz)" for t, o in sorted(out.items(), key=lambda kv: -kv[1]["score"])]
    print("\n".join(lines))
    print(f"::notice title=Quiz-Themen::{' ⏎ '.join(lines)[:3800]}")


if __name__ == "__main__":
    main()
