"""
Abteilungen, Mitarbeiter und ihre festen Handgriffe (= GitHub-Workflows im Repo youtube-automatik).

external=True  -> wirkt nach außen (veröffentlicht, ändert Kanäle) -> braucht im Programm eine Freigabe per Klick.
"""
REPO = "McWiebel1995/youtube-automatik"


def job(id, label, workflow, inputs=None, external=False, hint=""):
    return {"id": id, "label": label, "workflow": workflow, "inputs": inputs or {}, "external": external, "hint": hint}


DEPTS = [
    {"id": "media", "name": "Medienhaus", "sub": "YouTube & Instagram · 10 Kanäle", "state": "live",
     "team": [
         {"name": "Lena", "role": "Calm-Haven-Produktion", "job": "Regen, Kamin, Wasser", "color": "#7cc4ff",
          "watch": ["produce.yml"],
          "jobs": [job("calm-all", "Fehlende Calm-Haven-Videos produzieren", "produce.yml",
                       {"channel": "alle", "dry_run": "false", "force": "false"}, True, "lädt nur hoch, wo heute noch nichts ist"),
                   job("calm-test", "Testlauf ohne Upload", "produce.yml", {"channel": "regen", "dry_run": "true"})]},
         {"name": "Ben", "role": "Kinder-Redaktion", "job": "Mondmelodie, Gute-Nacht-Kiste", "color": "#ff8fab",
          "watch": ["kids.yml"],
          "jobs": [job("kids-schlaf", "Mondmelodie produzieren", "kids.yml", {"job": "schlaf", "dry_run": "false"}, True),
                   job("kids-story", "Gute-Nacht-Geschichte produzieren", "kids.yml", {"job": "geschichten", "dry_run": "false"}, True),
                   job("kids-test", "Geschichte als Test (ohne Upload)", "kids.yml", {"job": "geschichten", "dry_run": "true"})]},
         {"name": "Kai", "role": "Wissensredaktion", "job": "Beyond the If", "color": "#ffc857",
          "watch": ["whatif.yml", "thumb-redo.yml"],
          "jobs": [job("wi-quiz", "Extra-Quiz veröffentlichen", "whatif.yml",
                       {"mode": "quiz", "dry_run": "false", "slot": "2"}, True, "nutzt den 2. Quiz-Platz des Tages"),
                   job("wi-news", "News-Short veröffentlichen", "whatif.yml", {"mode": "news-short", "dry_run": "false"}, True),
                   job("wi-video-test", "Langes Video als Test (ohne Upload)", "whatif.yml", {"mode": "video", "dry_run": "true"}),
                   job("wi-thumbs", "Thumbnails der langen Videos erneuern", "thumb-redo.yml", {"days": "14"}, True)]},
         {"name": "Mia", "role": "Social Media", "job": "Instagram-Reels & Abgleich", "color": "#ff7ac6",
          "watch": ["ig-sync.yml", "instagram-post.yml", "astro.yml"],
          "jobs": [job("ig-list", "Abgleich YouTube ↔ Instagram anzeigen", "ig-sync.yml", {"mode": "list"}),
                   job("ig-post", "Fehlende Reels nachholen", "ig-sync.yml", {"mode": "post"}, True),
                   job("astro", "dear.zodiac-Karussell posten", "astro.yml", {"dry_run": "false"}, True)]},
         {"name": "Tom", "role": "Community", "job": "Kommentare beantworten", "color": "#5ce0c0",
          "watch": ["comments.yml"],
          "jobs": [job("cm-suggest", "Neue Kommentar-Vorschläge holen", "comments.yml", {"mode": "suggest"})]},
         {"name": "Ida", "role": "Analyse", "job": "Montagsbericht, Quiz-Themen", "color": "#b9a6ff",
          "watch": ["analytics.yml"],
          "jobs": [job("an-run", "Auswertung jetzt erstellen", "analytics.yml")]},
         {"name": "Jonas", "role": "Ruhige Gedanken", "job": "Gedanken-Videos", "color": "#a7d98a",
          "watch": ["gedanken.yml"],
          "jobs": [job("gd-test", "Testlauf (ohne Upload)", "gedanken.yml", {"dry_run": "true"}),
                   job("gd-pub", "Video veröffentlichen", "gedanken.yml", {"dry_run": "false"}, True)]},
     ]},
    {"id": "shop", "name": "Tacticn Shop", "sub": "tacticn.de · Lovable ↔ GitHub (tactical-symbol-hub)", "state": "live",
     "repo": "McWiebel1995/tactical-symbol-hub",
     "team": [{"name": "Max", "role": "Shop-Entwickler", "job": "Neues Shopsystem", "color": "#9bc46b", "jobs": []},
              {"name": "Jan", "role": "Produktpflege", "job": "Symbole & Sets", "color": "#c9d48a",
               "watch": ["tacticn-quiz.yml"],
               "jobs": [job("tq-next", "Quiz-Reel bauen (nächstes Zeichen)", "tacticn-quiz.yml",
                            {"symbol": "zufall", "probe": "false"}, False, "1 Zeichen pro Video · Vorschau unter Releases")]},
              {"name": "Sara", "role": "Kundenservice", "job": "Fragen & Downloads", "color": "#8fd1a8", "jobs": []}]},
    {"id": "cicco", "name": "CICCO Feinkost", "sub": "cicco-fam.de · Lovable ↔ GitHub (ciccone-kitchen-stories)", "state": "live",
     "repo": "McWiebel1995/ciccone-kitchen-stories",
     "team": [{"name": "Gio", "role": "Shop-Pflege", "job": "Produkte, Preise, Allergene", "color": "#e0a96b", "jobs": []},
              {"name": "Rosa", "role": "Rezepte & Journal", "job": "Inhalte für Instagram", "color": "#f2c38b", "jobs": []}]},
    {"id": "kdp", "name": "KDP-Verlag", "sub": "Amazon-Bücher", "state": "plan",
     "team": [{"name": "Eva", "role": "Lektorat", "job": "Manuskripte prüfen", "color": "#7fd3e6", "jobs": []},
              {"name": "Leo", "role": "Cover", "job": "Cover & Klappentext", "color": "#d9b44a", "jobs": []},
              {"name": "Nora", "role": "Veröffentlichung", "job": "Upload über Chrome", "color": "#9aa8ff", "jobs": []}]},
    {"id": "finance", "name": "Rechnungsabteilung", "sub": "Cicco UG · Belege & Fristen", "state": "warn",
     "team": [{"name": "Paul", "role": "Belegprüfung", "job": "Sortieren, an lexoffice", "color": "#d8d3c4", "jobs": []},
              {"name": "Ute", "role": "Fristen", "job": "USt, Abschluss, Offenlegung", "color": "#ffb454", "jobs": []},
              {"name": "Rolf", "role": "Kostenwächter", "job": "Modal, Abos, Domains", "color": "#8be08b", "jobs": []}]},
    {"id": "cliplab", "name": "The Clip Lab", "sub": "Clipping-Kampagnen · TikTok, Instagram, YouTube", "state": "live",
     "team": [{"name": "Nico", "role": "Cutter", "job": "Clips aus Kampagnen-Material", "color": "#ff9f6b",
               "watch": ["cliplab.yml"],
               "jobs": [job("cl-cut", "Neue Clips schneiden (zur Freigabe)", "cliplab.yml", {"mode": "cut"}),
                        job("cl-due", "Freigegebene Clips jetzt posten", "cliplab.yml", {"mode": "due"}, True,
                            "sonst automatisch zur US-Abendzeit"),
                        job("cl-probe", "Zugänge & Material prüfen", "cliplab.yml", {"mode": "probe"})]},
              {"name": "Lia", "role": "Kampagnen & Einreichung", "job": "Content Rewards, Whop", "color": "#ffd36b",
               "jobs": []}]},
    {"id": "gaming", "name": "Gaming-Studio", "sub": "News-Shorts zu Spielen", "state": "plan",
     "team": [{"name": "Finn", "role": "Gaming-Redaktion", "job": "News-Shorts (Test)", "color": "#7bdcff",
               "watch": ["gaming.yml"],
               "jobs": [job("gm-test", "News-Short als Test bauen", "gaming.yml", {"publish": "false"})]}]},
    {"id": "legal", "name": "Rechtsabteilung", "sub": "Impressum, Kennzeichnung, Rechtstexte", "state": "warn",
     "team": [{"name": "Clara", "role": "Impressum-Wächter", "job": "Kanäle & Videos prüfen", "color": "#c9b6ff",
               "watch": ["legal.yml"],
               "jobs": [job("lg-check", "Impressum-Zeilen zählen", "legal.yml", {"dry_run": "true"}),
                        job("lg-fix", "Impressum-Zeilen entfernen (nächste 50)", "legal.yml", {"dry_run": "false"}, True,
                            "ändert Videobeschreibungen, max. 50 pro Lauf")]},
              {"name": "Felix", "role": "Suchoptimierung & Texte", "job": "Beschreibungen, Stichwörter", "color": "#a5b4fc",
               "watch": ["seo-backfill.yml"],
               "jobs": [job("seo-test", "Suchbegriffe-Probe (letzte 7 Tage)", "seo-backfill.yml",
                            {"days": "7", "dry_run": "true", "shorts": "true"})]}]},
    {"id": "lab", "name": "Ideenlabor", "sub": "Neue Kanäle & Tests", "state": "plan",
     "team": [{"name": "Zoe", "role": "Ideenscout", "job": "Trends & Nischen", "color": "#ff9fd0", "jobs": []}]},
    {"id": "engine", "name": "Maschinenraum", "sub": "GitHub Actions · Modal-GPU", "state": "live",
     "team": [{"name": "Otto", "role": "Technik", "job": "Zeitpläne, Tokens, Kontingent", "color": "#8be08b",
               "watch": ["check-tokens.yml", "studio.yml"],
               "jobs": [job("tk-check", "Alle YouTube-Zugänge prüfen", "check-tokens.yml"),
                        job("studio", "Kanaldaten neu sammeln", "studio.yml")]}]},
]

START_TASKS = [
    {"t": "cicco-fam.de auf UG mit MwSt umstellen", "dept": "cicco", "who": "du"},

    {"t": "tacticn.de-Impressum auf UG-Angaben prüfen", "dept": "legal", "who": "du"},

    {"t": "Ruhige Gedanken: Testlauf, Ursache für Zeitüberschreitung finden", "dept": "media", "who": "Jonas"},

]


def find(job_id):
    for d in DEPTS:
        for w in d["team"]:
            for j in w.get("jobs", []):
                if j["id"] == job_id:
                    return j
    return None
