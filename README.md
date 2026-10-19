# 🌧️🔥💧 Relax Sounds & 🌙 Kinderkanäle – automatische YouTube-Produktion

Erzeugt automatisch neue Videos für **sechs Kanäle** (3× Entspannung, 3× Kinder)
und lädt sie auf YouTube hoch – komplett über **GitHub Actions**, ohne eigenen Server.

| Kanal (Schlüssel) | Name auf YouTube | Inhalt |
|---|---|---|
| **regen** | Calm Haven Rain | Regen, Dachregen, Gewitter, Wind |
| **kamin** | Calm Haven Fireside | Kaminfeuer, Wind, Regen, Uhrticken |
| **wasserfall** | Calm Haven Waters | Wasserfall, Bach, Vögel, Wind |

Die **Relax-Kanäle sind komplett auf Englisch** (Titel, Beschreibung, Tags, Thumbnail „3 HOURS“) –
für ein weltweites Publikum und höhere Werbeeinnahmen. Die **Kinderkanäle sind auf Deutsch**.
Namen und Texte änderst du in `config/channels.yaml` bzw. `config/kids.yaml`.

**Du musst keine Dateien erstellen.**
- **Sounds:** **echte Natur-Aufnahmen** von Freesound.org (nur Lizenz CC0 = gemeinfrei), automatisch zu nahtlosen Loops geschnitten.
  Dafür einen kostenlosen Schlüssel holen: <https://freesound.org/apiv2/apply> → Secret `FREESOUND_API_KEY`.
  Ohne Schlüssel werden selbst erzeugte Sounds verwendet.
- **Bilder:** **echte Natur-Videos** von Pixabay und/oder Pexels (kostenlos, kommerziell nutzbar),
  automatisch zu nahtlosen 1080p-Loops geschnitten. Dafür brauchst du nur einen kostenlosen API-Schlüssel.
  Ohne Schlüssel werden selbst gezeichnete Animationen verwendet.

---

## So funktioniert es

```
gen_audio.py  ──►  Sound-Loops (je Kanal 4 Sounds × 3 Varianten)
fetch_stock.py ─►  echte Natur-Videos (je Kanal 8 Clips) – bevorzugt
gen_video.py  ──►  gezeichnete Ersatz-Szenen, falls kein Schlüssel
                        │
pipeline.py   ──►  zufällige Mischung: Basis-Sound + Extras mit eigener Lautstärke
                   + zufällige Szene + Titel/Beschreibung + Thumbnail
                        │
upload.py     ──►  YouTube (privat hochgeladen, automatisch veröffentlicht um 18:00 UTC)
```

Jedes Video ist eine **eigene Mischung** (andere Ebenen, Lautstärken, Szene, Länge, Titel).
Das ist wichtig, weil YouTube massenhaft gleiche Videos nicht monetarisiert.

---

## Einrichtung (einmalig, ca. 30–45 Minuten)

### 1. Repository auf GitHub anlegen
Neues Repo erstellen und diesen Ordner hochladen.

> **Öffentlich oder privat?** Bei **öffentlichen** Repos sind GitHub-Actions-Minuten unbegrenzt kostenlos.
> Private Repos haben nur 2.000 Minuten/Monat gratis – für 6 Kanäle reicht das meist **nicht**.
> Deine Zugangsdaten liegen als Secrets geschützt und sind auch bei öffentlichen Repos nicht sichtbar.
> Alternative: privat + GitHub Pro (3.000 Minuten) und seltener hochladen.

### 2. Google-Cloud-Projekt & YouTube-API (geht am Handy, im Browser)
1. <https://console.cloud.google.com> öffnen (Browser auf „Desktop-Version“ stellen hilft) → **neues Projekt**
2. **APIs & Dienste → Bibliothek → „YouTube Data API v3“ → Aktivieren**
3. **OAuth-Zustimmungsbildschirm / Google Auth Platform**: Typ „Extern“, App-Name (z. B. „Calm Haven Uploader“), deine E-Mail eintragen
4. **Wichtig:** unter *Zielgruppe* auf **„App veröffentlichen“ / „In Produktion“** stellen.
   Im Status „Testen“ laufen die Tokens nach **7 Tagen** ab.
5. **Clients → Client erstellen → Anwendungstyp: „Fernseher und Geräte mit begrenzter Eingabe“**
   → Client-ID und Clientschlüssel kopieren

### 3. GitHub-Secrets eintragen (Teil 1)
Repo → **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Inhalt |
|---|---|
| `YT_CLIENT_ID` | Client-ID aus Schritt 2 |
| `YT_CLIENT_SECRET` | Clientschlüssel aus Schritt 2 |
| `GH_PAT` | GitHub-Token, damit der Token-Workflow die Kanal-Tokens speichern kann (siehe unten) |
| `PIXABAY_API_KEY` | **empfohlen** für echte Videos, kostenlos: <https://pixabay.com/api/docs/> |
| `PEXELS_API_KEY` | *optional* für noch mehr echte Videos: <https://www.pexels.com/api/> |
| `ANTHROPIC_API_KEY` | *optional*, nur für neue KI-Geschichten |

**`GH_PAT` erstellen:** GitHub → Profilbild → Settings → Developer settings → Personal access tokens →
**Fine-grained tokens → Generate new token** → *Repository access:* nur dieses Repo →
*Permissions:* **Secrets → Read and write** → Generate → Token kopieren und als Secret `GH_PAT` speichern.

### 4. Kanal-Tokens holen – komplett am Handy (6× je 1 Minute)
1. Repo → **Actions → „🔑 Token holen“ → Run workflow** → Kanal auswählen → **Run workflow**
2. Den gestarteten Lauf öffnen → Job **token** → Schritt **„Mit YouTube verbinden“** aufklappen
3. Dort steht ein Code. **google.com/device** öffnen, Code eingeben, mit Google anmelden,
   **den passenden Kanal auswählen** und zulassen (Warnung „nicht verifiziert“ → *Erweitert → Weiter*)
4. Nach ein paar Sekunden: ✅ *Verbunden mit Kanal …* – das Token ist automatisch als Secret gespeichert.
5. Für alle 6 Kanäle wiederholen.

### 5. Testlauf
Repo → **Actions → „Videos produzieren & hochladen“ → Run workflow** (Testlauf ist vorausgewählt).
Unter dem Lauf liegen danach Thumbnail, Titel und ein 3-Minuten-Testvideo zum Download.

Wenn alles passt: Ab dann läuft es **jeden Tag automatisch um 05:07 Uhr** (deutsche Sommerzeit).

---

## 🧸 Kinderkanäle

| Kanal | Inhalt | Rhythmus |
|---|---|---|
| **schlaf** (Mondmelodie) | eigene Spieluhr-Schlaflieder + Sternenhimmel, 1–3 h, optional leises Rauschen | alle 2 Tage |
| **lernen** (Lernbärchen) | Zahlen, Farben, Formen mit Sprecherstimme, Animation und Quiz | täglich 1 Short, Mo+Do 1 langes Video |
| **geschichten** (Gute-Nacht-Kiste) | Gute-Nacht-Geschichten vorgelesen, mit Untertiteln und Bilderbuch-Szene | So, Di, Fr |

- **Alles wird als „Speziell für Kinder“ markiert und PRIVAT hochgeladen.**
  Du schaust dir jedes Video in der **YouTube-Studio-App** kurz an und stellst es auf „Öffentlich“.
  Das schützt dich vor Fehlern und ist bei Kinderinhalten sehr wichtig.
- Sprecherstimme: **Piper** (offline, kostenlos, natürliche deutsche Stimmen) – Stimme in `config/kids.yaml` wählbar.
- Spieluhr-Melodien werden bei jedem Video **neu komponiert** (eigene Musik, keine Lizenzprobleme).
- Geschichten: 8 fertige Geschichten liegen in `data/stories.yaml`. Neue einfach anhängen.
  Bereits verwendete werden in `data/stories_used.json` gemerkt.
  Mit `ai_stories: true` in `config/kids.yaml` + Secret `ANTHROPIC_API_KEY` schreibt Claude neue Geschichten.
- Hinweis: Videos „Speziell für Kinder“ haben keine Kommentare und keine personalisierte Werbung,
  dadurch verdienen sie pro Aufruf weniger als normale Videos.

**Testlauf:** Actions → „Kinder-Videos produzieren“ → Run workflow → Auftrag wählen (Testlauf ist vorausgewählt).

```bash
# lokal
pip install -r requirements.txt -r requirements-kids.txt
python scripts/kids/pipeline_kids.py --channel lernen --format short --topic farben --dry-run
python scripts/kids/pipeline_kids.py --channel geschichten --dry-run
python scripts/kids/pipeline_kids.py --channel schlaf --dry-run --minutes 3
```

---

## ⚠️ Wichtige YouTube-Grenzen

- **Kontingent:** Uploads haben laut aktueller API-Doku ein eigenes Tageslimit pro Projekt
  (derzeit 100 Uploads/Tag). 5–7 Videos pro Tag sind also kein Problem.
- Falls deine ersten Videos trotzdem dauerhaft „privat“ bleiben: in YouTube Studio prüfen,
  ob der Kanal Einschränkungen hat, und notfalls einmal von Hand auf „öffentlich“ stellen.
- **Eigene Thumbnails** gehen erst, wenn der Kanal per Telefon verifiziert ist: <https://www.youtube.com/verify>
- **Monetarisierung:** YouTube prüft den ganzen Kanal. Ab und zu ein Community-Post, eigene
  Playlists, ein Kanal-Trailer und Antworten auf Kommentare helfen sehr.

---

## Anpassen

Alles Wichtige steht in **`config/channels.yaml`**:
- Titel-Vorlagen, Szenen-Namen, Tags
- Sound-Ebenen mit Lautstärkebereich und Wahrscheinlichkeit
- Videolängen (`durations_hours`) und Veröffentlichungszeit (`publish_time_utc`)
- `playlist_id` – neue Videos automatisch in eine Playlist

Uploadrhythmus ändern: in `.github/workflows/produce.yml` die `cron`-Zeile anpassen
(z. B. `"7 3 */2 * *"` = alle 2 Tage).

Eigene Schriftart fürs Thumbnail: als `assets/fonts/Thumbnail.ttf` ablegen.

### Lokal testen
```bash
pip install -r requirements.txt          # ffmpeg muss installiert sein
python scripts/gen_audio.py
python scripts/gen_video.py
python scripts/pipeline.py --channel regen --dry-run --minutes 2
```
Ergebnis liegt in `output/`.

---

## Dateien

| Datei | Aufgabe |
|---|---|
| `scripts/gen_audio.py` | erzeugt Regen, Donner, Wind, Feuer, Wasserfall, Bach, Vögel, Uhr |
| `scripts/gen_video.py` | erzeugt nahtlose Video-Loops für die drei Szenen |
| `scripts/fetch_sounds.py` | echte Natur-Aufnahmen (Ton) von Freesound, nur CC0 |
| `scripts/fetch_stock.py` | echte Videos von Pixabay/Pexels als nahtlose Loops (bis 60 s) |
| `scripts/render.py` | mischt die Ebenen, normalisiert die Lautstärke, baut das Video |
| `scripts/metadata.py` | Titel, Beschreibung, Tags |
| `scripts/thumbnail.py` | Vorschaubild 1280×720 |
| `scripts/upload.py` | YouTube-Upload mit Wiederholung bei Fehlern |
| `scripts/pipeline.py` | verbindet alles |
| `scripts/get_token.py` | Token am PC holen (Alternative) |
| `scripts/device_token.py` + `.github/workflows/token.yml` | Token am Handy holen, speichert direkt als Secret |
| `.github/workflows/produce.yml` | täglicher Automatik-Lauf (Relax) |
| `scripts/kids/music.py` | komponiert Spieluhr-Schlaflieder |
| `scripts/kids/visuals.py` | Sternenhimmel & Bilderbuch-Szene |
| `scripts/kids/drawing.py` | Figuren, Formen, Beispiele (Sonne, Erdbeere, Schweinchen …) |
| `scripts/kids/learn.py` | Lernvideos & Shorts (Zahlen, Farben, Formen) |
| `scripts/kids/stories.py` | Geschichten vorlesen, Untertitel, optional KI-Geschichten |
| `scripts/kids/tts.py` | Sprachausgabe (Piper) |
| `scripts/kids/pipeline_kids.py` | verbindet alles für die Kinderkanäle |
| `config/kids.yaml` | Einstellungen der Kinderkanäle |
| `data/stories.yaml` | Geschichten-Sammlung |
| `.github/workflows/kids.yml` | Automatik-Lauf der Kinderkanäle |
