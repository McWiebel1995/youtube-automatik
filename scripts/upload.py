"""Lädt ein Video per YouTube Data API v3 hoch (geplant veröffentlicht)."""
import os
from pathlib import Path
import random
import time

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube"]
RETRY_STATUS = {500, 502, 503, 504}


def service(refresh_token):
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=None,          # alle freigegebenen Berechtigungen nutzen (youtube, force-ssl, analytics)
    )
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def check_channel(yt, channel):
    """Sicherheitscheck: bricht ab, wenn das Token zu einem anderen Kanal gehört."""
    res = yt.channels().list(part="snippet", mine=True).execute()
    title = (res.get("items") or [{}])[0].get("snippet", {}).get("title", "")
    norm = lambda s: "".join(ch for ch in s.lower() if ch.isalnum())  # noqa: E731
    if not title or (norm(channel["name"]) not in norm(title) and norm(title) not in norm(channel["name"])):
        raise SystemExit(f"❌ Abbruch: Token gehört zum Kanal »{title}«, erwartet »{channel['name']}«. "
                         f"Bitte {channel['token_secret']} neu holen.")
    print(f"  Kanal geprüft: {title}")


LAST_DIR = Path(__file__).resolve().parent.parent / "data" / "last_upload"


def _today():
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")


def uploaded_today(channel_key):
    """True, wenn für diesen Kanal heute (UTC) schon hochgeladen wurde (verhindert Doppel-Uploads, falls ein
    verspäteter Zeitplan-Lauf nach einem manuellen Lauf doch noch startet). Eine Datei pro Kanal."""
    f = LAST_DIR / f"{channel_key}.txt"
    return f.exists() and f.read_text().strip() == _today()


def mark_uploaded(channel_key):
    LAST_DIR.mkdir(parents=True, exist_ok=True)
    (LAST_DIR / f"{channel_key}.txt").write_text(_today() + "\n")


SYNTHETIC = {"whatif", "lernen", "geschichten"}   # KI-Stimme erzählt bzw. realistische KI-Szenen -> YouTube-Kennzeichnung


def synthetic(channel):
    """YouTube verlangt die Kennzeichnung bei synthetischer Erzählstimme und realistischen KI-Szenen."""
    if "synthetic" in channel:
        return bool(channel["synthetic"])
    try:
        import hashtags
        return hashtags.channel_of(name=channel.get("name", "")) in SYNTHETIC
    except Exception:  # noqa: BLE001
        return False


def upload(yt, video_path, meta, channel, publish_at=None):
    try:                                              # Hashtags passend zu Kanal & Video (max. 3, siehe hashtags.py)
        import hashtags
        meta = hashtags.yt_meta(meta, channel.get("name", ""))
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ Hashtags: {e}")
    status = {
        "privacyStatus": "private" if publish_at else channel.get("privacy", "private"),
        "selfDeclaredMadeForKids": bool(channel.get("made_for_kids", False)),
        "containsSyntheticMedia": synthetic(channel),
    }
    if publish_at:
        status["publishAt"] = publish_at
    body = {
        "snippet": {
            "title": meta["title"],
            "description": meta["description"],
            "tags": meta["tags"],
            "categoryId": str(channel.get("category_id", "10")),
            "defaultLanguage": channel.get("language", "de"),
            "defaultAudioLanguage": channel.get("language", "de"),
        },
        "status": status,
    }
    media = MediaFileUpload(str(video_path), chunksize=16 * 1024 * 1024, resumable=True,
                            mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)

    response, attempt = None, 0
    while response is None:
        try:
            st, response = req.next_chunk()
            if st:
                print(f"  Upload {int(st.progress() * 100)} %", flush=True)
        except HttpError as e:
            if e.resp.status not in RETRY_STATUS or attempt >= 8:
                raise
            attempt += 1
            wait = min(60, 2 ** attempt) + random.random()
            print(f"  Serverfehler {e.resp.status}, neuer Versuch in {wait:.0f}s")
            time.sleep(wait)
        except (ConnectionError, TimeoutError, OSError) as e:   # Verbindungsabbruch (SSL/Socket) -> fortsetzen
            if attempt >= 8:
                raise
            attempt += 1
            wait = min(60, 2 ** attempt) + random.random()
            print(f"  Verbindung unterbrochen ({type(e).__name__}), setze Upload in {wait:.0f}s fort")
            time.sleep(wait)
    _archive_short(video_path, response["id"], meta)
    return response["id"]


def _archive_short(path, vid, meta):
    """Shorts zusätzlich als Release-Anhang ablegen (Tag yt-shorts, Name <videoId>.mp4) –
    so kann der Abgleich YouTube ↔ Instagram (ig_sync.py) sie später ohne YouTube-Download posten."""
    try:
        import subprocess
        if "#shorts" not in (meta.get("title", "") + meta.get("description", "")).lower():
            dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                        str(path)], capture_output=True, text=True).stdout or 999)
            if dur > 180:
                return
        repo = os.environ.get("GITHUB_REPOSITORY")
        if not (repo and os.environ.get("GH_TOKEN")):
            return
        if subprocess.run(["gh", "release", "view", "yt-shorts", "--repo", repo], capture_output=True).returncode:
            subprocess.run(["gh", "release", "create", "yt-shorts", "--repo", repo, "--prerelease", "--title",
                            "YouTube-Shorts (Archiv)", "--notes", "Kopien der hochgeladenen Shorts für den Instagram-Abgleich."],
                           capture_output=True)
        tmp = Path(path).with_name(f"{vid}.mp4")
        if tmp != Path(path):
            tmp.write_bytes(Path(path).read_bytes())
        subprocess.run(["gh", "release", "upload", "yt-shorts", str(tmp), "--clobber", "--repo", repo], capture_output=True)
        print(f"  🗄 Short archiviert ({vid})")
    except Exception as e:  # noqa: BLE001 – darf den Upload nie stören
        print(f"  ⚠ Short-Archiv: {e}")


def set_thumbnail(yt, video_id, thumb_path):
    try:
        yt.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumb_path))).execute()
        return True
    except HttpError as e:
        # Eigene Thumbnails gehen erst nach Telefon-Verifizierung des Kanals
        print(f"  ⚠ Thumbnail nicht gesetzt ({e.resp.status}). Kanal verifiziert? youtube.com/verify")
        return False


def recent_titles(yt, n=40):
    c = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
    pl = c["contentDetails"]["relatedPlaylists"]["uploads"]
    items = yt.playlistItems().list(part="snippet", playlistId=pl, maxResults=min(50, n)).execute().get("items", [])
    return {i["snippet"]["title"].strip().lower() for i in items}


def unique_title(make, recent, rnd, suffixes, tries=15):
    """make() liefert ein Metadaten-Dict mit 'title'. Wiederholt, bis der Titel neu ist; sonst Zusatz anhängen."""
    meta = make()
    for _ in range(tries):
        if meta["title"].strip().lower() not in recent:
            return meta
        meta = make()
    for suf in rnd.sample(suffixes, len(suffixes)):
        t = f"{meta['title']} {suf}"[:100]
        if t.strip().lower() not in recent:
            meta["title"] = t
            return meta
    return meta


PLAYLIST_DIR = Path(__file__).resolve().parent.parent / "data" / "playlists"


def ensure_playlist(yt, key, title, description, made_for_kids=False):
    """Legt pro Kanal einmal eine Playlist an (ID in data/playlists/<key>.txt) und gibt die ID zurück."""
    f = PLAYLIST_DIR / f"{key}.txt"
    if f.exists() and f.read_text().strip():
        return f.read_text().strip()
    body = {"snippet": {"title": title, "description": description},
            "status": {"privacyStatus": "public"}}
    pid = yt.playlists().insert(part="snippet,status", body=body).execute()["id"]
    PLAYLIST_DIR.mkdir(parents=True, exist_ok=True)
    f.write_text(pid + "\n")
    return pid


def add_to_playlist(yt, video_id, playlist_id):
    if not playlist_id:
        return
    yt.playlistItems().insert(part="snippet", body={"snippet": {
        "playlistId": playlist_id,
        "resourceId": {"kind": "youtube#video", "videoId": video_id},
    }}).execute()
