#!/usr/bin/env python3
"""Einmalig: ausdrucksstarke Referenzstimmen für Anime-Figuren (Gemini-TTS mit Schauspiel-Anweisung).
Chatterbox übernimmt von der Referenz Klang UND Spielweise -> lebendigere Synchro."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import gtts  # noqa: E402

OUT = ROOT / "data" / "voices" / "anime"
OUT.mkdir(parents=True, exist_ok=True)
LINE = ("No... I won't run. Not tonight. You think you can take everything from us? Then come and try! "
        "Because I swear, as long as I'm still standing, nobody touches this place!")
ROLES = {   # Datei: (Gemini-Stimme, Schauspiel-Anweisung)
    "male_low": ("Algenib", "a gruff, battle-worn anime hero in his thirties, intense and emotional, voice cracking with anger, like a dramatic 90s anime English dub"),
    "male_mid": ("Fenrir", "a passionate young anime hero, fiery, out of breath, shouting the last sentence with full conviction, like a 90s anime English dub"),
    "male_high": ("Puck", "a cocky teenage anime rival, energetic and loud, slightly arrogant, like a 90s anime English dub"),
    "villain": ("Charon", "a cold, menacing anime villain, slow, mocking and dangerous, quiet intensity, like a 90s anime English dub"),
    "female_mid": ("Kore", "a fierce, determined young anime heroine, emotional and strong, shouting with tears in her voice, like a 90s anime English dub"),
    "female_high": ("Leda", "an energetic teenage anime girl, brave but scared, emotional and loud, like a 90s anime English dub"),
    "old_male": ("Orus", "a wise old anime mentor, deep, calm but powerful, every word heavy with meaning, like a 90s anime English dub"),
}
NARR = ("Imagine you wake up tomorrow, and the Moon is simply gone. No explosion, no warning. "
        "At first, almost nothing changes. But within hours, the oceans begin to behave very differently.")
ROLES["narrator"] = ("Charon", "a captivating science documentary narrator: curious, warm, clear, with subtle "
                     "suspense and natural pauses, like a top YouTube science channel")
for name, (voice, direction) in ROLES.items():
    f = OUT / f"{name}.wav"
    if f.exists():
        continue
    style = f"Perform this as {direction}. Real voice acting, not flat reading:\n\n"
    gtts.synth(NARR if name == "narrator" else LINE, voice, f, style=style)
    print("✓", name)
    import time
    time.sleep(gtts.GAP_S)
