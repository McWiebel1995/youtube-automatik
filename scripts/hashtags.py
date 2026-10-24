#!/usr/bin/env python3
"""
Hashtags passend zu Kanal UND Video – zentral, kurz vor jedem Upload/Post angewendet.

Regeln (Stand 2026):
  Instagram: höchstens 5 Hashtags pro Beitrag -> 1 Kanal-Kern + 2 zum Inhalt + 1 Zielgruppe + 1 wechselnder Nischen-Tag
  YouTube:   nur die ersten 3 Hashtags erscheinen über dem Titel; >15 Hashtags -> alle ignoriert
             -> genau 3 am Ende der Beschreibung (Inhalt, Kanal-Kern, #shorts bei Shorts)

Der Inhalt wird aus Titel/Beschreibung erkannt (z. B. "forest", "Zahlen", "Koala", "black hole").
Welche Nischen-Tags gerade getestet werden, wechselt zufällig -> data/stats kann später zeigen, was zieht.
"""
import random
import re

# Kanal -> Kern, Zielgruppe, Nischen (Rotation), Inhalts-Stichwörter -> Hashtag
RULES = {
    "regen": {
        "core": "#rainsounds", "audience": "#sleepsounds",
        "niche": ["#asmrsleep", "#studyambience", "#rainyday", "#cozyvibes", "#relaxingsounds"],
        "content": [(r"forest|wood|jungle", "#forestrain"), (r"window|glass", "#rainonwindow"),
                    (r"thunder|storm", "#thunderstorm"), (r"city|street|skyline|urban", "#cityrain"),
                    (r"roof|porch|veranda|cabin", "#rainonroof"), (r"tent|camp", "#tentrain"),
                    (r"car", "#rainonacar"), (r"night", "#rainynight")],
        "fallback": ["#rain", "#rainsound"],
    },
    "kamin": {
        "core": "#fireplace", "audience": "#sleepsounds",
        "niche": ["#hygge", "#cozyvibes", "#ambience", "#relaxingsounds", "#asmr"],
        "content": [(r"cabin|hut|chalet", "#cabinvibes"), (r"autumn|fall|herbst", "#autumnvibes"),
                    (r"winter|snow|christmas", "#wintervibes"), (r"country|cottage|house|home", "#cozyhome"),
                    (r"rain", "#rainandfire"), (r"camp", "#campfire")],
        "fallback": ["#cracklingfire", "#cozy"],
    },
    "wasserfall": {
        "core": "#naturesounds", "audience": "#sleepsounds",
        "niche": ["#whitenoise", "#meditation", "#focusmusic", "#calm", "#relaxingsounds"],
        "content": [(r"waterfall", "#waterfallsounds"), (r"stream|creek|brook", "#streamsounds"),
                    (r"river", "#riversounds"), (r"bird", "#birdsong"), (r"forest", "#forestsounds"),
                    (r"mountain", "#mountainwaterfall"), (r"ocean|sea|wave", "#oceansounds")],
        "fallback": ["#watersounds", "#waterfall"],
    },
    "schlaf": {
        "core": "#einschlafmusik", "audience": "#mamaleben",
        "niche": ["#babyschlaf", "#babyeinschlafen", "#gutenacht", "#schlafenszeit", "#elternalltag"],
        "content": [(r"spieluhr", "#spieluhr"), (r"schlaflied|wiegenlied", "#schlaflied"),
                    (r"stern|mond|himmel", "#sternenhimmel"), (r"regen", "#regengeräusche"),
                    (r"meer|wellen", "#meeresrauschen")],
        "fallback": ["#spieluhr", "#schlaflied"],
    },
    "lernen": {
        "core": "#kleinkind", "audience": "#elternalltag",
        "niche": ["#montessorizuhause", "#kitaideen", "#lernenmitspass", "#frühförderung", "#mamaleben"],
        "content": [(r"zähl|zahl|bis \d", "#zahlenlernen"), (r"farbe|rot|blau|gelb|grün|lila|orange", "#farbenlernen"),
                    (r"form|kreis|dreieck|quadrat|stern|herz|oval|rechteck", "#formenlernen"),
                    (r"quiz|rate", "#rätselfürkinder")],
        "fallback": ["#lernenmitkindern", "#kinderlernen"],
    },
    "geschichten": {
        "core": "#gutenachtgeschichte", "audience": "#abendritual",
        "niche": ["#einschlafgeschichte", "#kindergeschichten", "#vorlesen", "#mamaleben", "#elternalltag"],
        "content": [(r"bär|hase|fuchs|igel|koala|eule|maus|katze|hund|elefant|löwe|pinguin|reh|eichhörnchen|schaf",
                     "#tiergeschichten"),
                    (r"winter|schnee|weihnacht", "#wintergeschichte"), (r"herbst|blätter|laub", "#herbstgeschichte"),
                    (r"mond|stern|wolke|traum", "#traumreise"), (r"meer|insel|wal|fisch", "#meeresgeschichte")],
        "fallback": ["#einschlafgeschichte", "#vorlesen"],
    },
    "whatif": {
        "core": "#whatif", "audience": "#sciencefacts",
        "niche": ["#science", "#didyouknow", "#curiosity", "#learnontiktok", "#mindblown"],
        "content": [(r"black hole", "#blackhole"), (r"moon", "#moon"), (r"\bsun\b|solar", "#solarsystem"),
                    (r"space|planet|galaxy|orbit|astronaut|mars", "#space"), (r"ocean|sea|tsunami", "#ocean"),
                    (r"dinosaur", "#dinosaurs"), (r"\bmatter\b", "#physics"), (r"\bbrain", "#brain"), (r"human body|\bblood\b|\bheart\b|\bcells?\b|\borgans?\b", "#humanbody"),
                    (r"antimatter|quantum|\batoms?\b|gravity|physics|speed of light", "#physics"),
                    (r"climate|weather|storm|volcano|earthquake", "#earthscience"),
                    (r"animal|species|evolution", "#animals"), (r"invent|technology|robot|\bai\b", "#technology"),
                    (r"quiz|trivia", "#quiz"), (r"news|today", "#sciencenews"), (r"earth", "#earth")],
        "fallback": ["#science", "#space"],
    },
}
ACCOUNT_CHANNEL = {"mondmelodie": "schlaf", "lernbaerchen": "lernen", "gutenacht": "geschichten", "whatif": "whatif"}
NAME_CHANNEL = [(r"rain", "regen"), (r"fireside|fire", "kamin"), (r"waters|water", "wasserfall"),
                (r"mondmelodie", "schlaf"), (r"lernbär", "lernen"), (r"gute-nacht|gutenacht", "geschichten"),
                (r"beyond", "whatif")]
TAG_RE = re.compile(r"(?<!\w)#[\wäöüÄÖÜß]+")


def channel_of(name="", account="", text=""):
    if account in ACCOUNT_CHANNEL:
        return ACCOUNT_CHANNEL[account]
    if account == "calmhaven":                         # ein IG-Konto für alle 3 Relax-Kanäle -> am Inhalt erkennen
        t = text.lower()
        return "kamin" if re.search(r"fire|kamin|🔥", t) else "wasserfall" if re.search(r"water|stream|🌊", t) else "regen"
    for pat, ch in NAME_CHANNEL:
        if re.search(pat, (name or "").lower()):
            return ch
    return None


def _content_tags(ch, text, n):
    t = TAG_RE.sub(" ", text.lower())
    out = []
    for pat, tag in RULES[ch]["content"]:
        if re.search(pat, t) and tag not in out:
            out.append(tag)
    for tag in RULES[ch]["fallback"]:
        if len(out) >= n:
            break
        if tag not in out:
            out.append(tag)
    return out[:n]


def strip(text):
    """Alle Hashtags entfernen, reine Hashtag-Zeilen löschen."""
    lines = [TAG_RE.sub("", ln).rstrip() if TAG_RE.search(ln) else ln for ln in text.split("\n")]
    out = "\n".join(ln for ln, orig in zip(lines, text.split("\n")) if ln.strip() or not TAG_RE.search(orig))
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def ig(ch, text, rnd=random):
    r = RULES[ch]
    tags = [r["core"]] + [t for t in _content_tags(ch, text, 3) if t != r["core"]][:2] + [r["audience"]]
    niche = [t for t in r["niche"] if t not in tags]
    tags.append(rnd.choice(niche))
    seen, res = set(), []
    for t in tags:
        if t.lower() not in seen:
            seen.add(t.lower())
            res.append(t)
    return res[:5]


def yt(ch, text, short=False, exclude=""):
    """Reihenfolge = Wichtigkeit; Hashtags, die schon im Titel stehen, werden übersprungen."""
    r = RULES[ch]
    cand = [t for t in _content_tags(ch, text, 2) if t != r["core"]] + [r["core"]] + (["#shorts"] if short else []) \
        + [r["audience"]]
    out = []
    for t in cand:
        if t.lower() not in exclude.lower() and t not in out:
            out.append(t)
    return out[:3]


def ig_caption(caption, account, rnd=random):
    ch = channel_of(account=account, text=caption)
    if not ch:
        return caption
    body = strip(caption)
    return f"{body}\n\n{' '.join(ig(ch, caption, rnd))}"


def yt_meta(meta, channel_name):
    """Beschreibung: Hashtags raus, genau 3 passende ans Ende. Titel bleibt (max. 2 Hashtags im Titel)."""
    ch = channel_of(name=channel_name)
    if not ch:
        return meta
    title, desc = meta.get("title", ""), meta.get("description", "")
    short = "#shorts" in (title + desc).lower()
    tt = TAG_RE.findall(title)
    if len(tt) > 2:                                   # zu viele Hashtags im Titel wirken spammy
        for t in tt[2:]:
            title = title.replace(t, "")
        title = re.sub(r"\s{2,}", " ", title).strip()
    tags = yt(ch, f"{title}\n{desc}", short, exclude=title)
    meta = dict(meta, title=title, description=f"{strip(desc)}\n\n{' '.join(tags)}".strip())
    kw = [t.lstrip("#") for t in tags]
    meta["tags"] = list(dict.fromkeys((meta.get("tags") or []) + kw))[:30]
    return meta


if __name__ == "__main__":                            # kleine Vorschau
    print(ig_caption("Crackling fire, warm light, nowhere to be. 🔥 Cozy cabin evening\n\n#fireplace #cozy #a #b #c #d #e #f",
                     "calmhaven", random.Random(1)))
    print(yt_meta({"title": "Zählen bis 4! 🎈 #shorts #zahlenlernen", "description": "Gemeinsam zählen.\n\n#shorts #x"},
                  "Lernbärchen"))
