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
import time  # noqa: E402
for name, (voice, direction) in ROLES.items():
    f = OUT / f"{name}.wav"
    if f.exists():
        continue
    style = f"Perform this as {direction}. Real voice acting, not flat reading:\n\n"
    try:
        gtts.synth(NARR if name == "narrator" else LINE, voice, f, style=style)
    except Exception as e:  # noqa: BLE001
        print(f"::warning title=Referenz {name}::{str(e)[:300]}")
        break
    print("✓", name)
    import time
    time.sleep(gtts.GAP_S)


# ---------------------------------------------------------------- Japanisch (Rollen-Archetypen, keine echten Sprecher)
OUT_JA = ROOT / "data" / "voices" / "anime_ja"
OUT_JA.mkdir(parents=True, exist_ok=True)
LINE_JA = ("逃げない……今夜だけは絶対に逃げない！お前たちに全部奪わせてたまるか！"
           "俺がここに立っている限り、誰にもこの場所には触れさせない！")
LINE_JA_F = ("逃げない……今夜だけは絶対に逃げない！あなたたちに全部奪わせたりしない！"
             "私がここに立っている限り、誰にもこの場所には触れさせない！")
ROLES_JA = {
    "male_low": ("Algenib", "a hoarse, battle-hardened Japanese anime hero (seinen style), intense, voice cracking with rage", False),
    "male_mid": ("Fenrir", "a passionate young Japanese shonen hero, fiery, breathless, screaming the last line with everything he has", False),
    "male_high": ("Puck", "a cocky, energetic Japanese teenage rival, loud and arrogant, typical shonen anime delivery", False),
    "villain": ("Charon", "a cold, elegant Japanese anime villain, quiet, slow, mocking and menacing", False),
    "female_mid": ("Kore", "a fierce, determined Japanese anime heroine, emotional, shouting with tears in her voice", True),
    "female_high": ("Leda", "an energetic Japanese anime girl, brave but scared, bright and emotional", True),
    "old_male": ("Orus", "a deep, calm, wise old Japanese anime mentor, every word heavy and powerful", False),
}
for name, (voice, direction, fem) in ROLES_JA.items():
    f = OUT_JA / f"{name}.wav"
    if f.exists():
        continue
    style = (f"Speak in natural native Japanese as {direction}, exactly like a professional Japanese anime voice "
             "performance (original archetype, not imitating any real actor). Real acting:\n\n")
    try:
        gtts.synth(LINE_JA_F if fem else LINE_JA, voice, f, style=style)
        print("✓ ja", name)
    except Exception as e:  # noqa: BLE001 – z. B. Tageslimit: Rest beim nächsten Lauf
        print(f"::warning title=Referenz {name}::{str(e)[:300]}")
        break
    time.sleep(gtts.GAP_S)
