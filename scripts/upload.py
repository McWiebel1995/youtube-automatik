"""Lädt ein Video per YouTube Data API v3 hoch (geplant veröffentlicht)."""
import os
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
        scopes=SCOPES,
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


def uploaded_recently(yt, hours=10):
    """True, wenn auf dem Kanal in den letzten `hours` Stunden schon hochgeladen wurde (verhindert Doppel-Uploads,
    falls ein verspäteter Zeitplan-Lauf nach einem manuellen Lauf doch noch startet)."""
    import datetime as _dt
    c = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
    pl = c["contentDetails"]["relatedPlaylists"]["uploads"]
    items = yt.playlistItems().list(part="snippet", playlistId=pl, maxResults=3).execute().get("items", [])
    cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=hours)
    for it in items:
        t = _dt.datetime.fromisoformat(it["snippet"]["publishedAt"].replace("Z", "+00:00"))
        if t > cutoff:
            return True
    return False


def upload(yt, video_path, meta, channel, publish_at=None):
    status = {
        "privacyStatus": "private" if publish_at else channel.get("privacy", "private"),
        "selfDeclaredMadeForKids": bool(channel.get("made_for_kids", False)),
        "containsSyntheticMedia": False,
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
    media = MediaFileUpload(str(video_path), chunksize=64 * 1024 * 1024, resumable=True,
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
    return response["id"]


def set_thumbnail(yt, video_id, thumb_path):
    try:
        yt.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumb_path))).execute()
        return True
    except HttpError as e:
        # Eigene Thumbnails gehen erst nach Telefon-Verifizierung des Kanals
        print(f"  ⚠ Thumbnail nicht gesetzt ({e.resp.status}). Kanal verifiziert? youtube.com/verify")
        return False


def add_to_playlist(yt, video_id, playlist_id):
    if not playlist_id:
        return
    yt.playlistItems().insert(part="snippet", body={"snippet": {
        "playlistId": playlist_id,
        "resourceId": {"kind": "youtube#video", "videoId": video_id},
    }}).execute()
