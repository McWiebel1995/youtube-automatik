#!/usr/bin/env python3
"""
Produziert ein Video für einen Kanal und lädt es hoch.

    python scripts/pipeline.py --channel regen                # rendern + hochladen
    python scripts/pipeline.py --channel kamin --dry-run      # nur rendern, kein Upload
    python scripts/pipeline.py --channel wasserfall --hours 2 --minutes 0
    python scripts/pipeline.py --channel regen --dry-run --minutes 2   # kurzer Test

Benötigte Umgebungsvariablen für den Upload:
    YT_CLIENT_ID, YT_CLIENT_SECRET und das Refresh-Token des Kanals
    (Name steht in config/channels.yaml unter token_secret, z. B. YT_REFRESH_TOKEN_REGEN)
"""
import argparse
import datetime as dt
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(__file__))

import metadata  # noqa: E402
import render  # noqa: E402
import thumbnail  # noqa: E402
from common import ASSETS, OUTPUT, load_config  # noqa: E402


def next_publish_time(time_utc, days_ahead):
    hh, mm = map(int, time_utc.split(":"))
    now = dt.datetime.now(dt.timezone.utc)
    when = (now + dt.timedelta(days=days_ahead)).replace(hour=hh, minute=mm, second=0, microsecond=0)
    if when <= now + dt.timedelta(minutes=30):
        when += dt.timedelta(days=1)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--channel", required=True)
    ap.add_argument("--hours", type=float, help="Länge in Stunden (sonst zufällig aus der Konfig)")
    ap.add_argument("--minutes", type=float, help="Länge in Minuten (für Tests, überschreibt --hours)")
    ap.add_argument("--seed", type=int, help="fester Zufallswert (reproduzierbar)")
    ap.add_argument("--publish-days", type=int, default=0, help="Veröffentlichung in N Tagen")
    ap.add_argument("--dry-run", action="store_true", help="nicht hochladen")
    ap.add_argument("--keep", action="store_true", help="Videodatei nach Upload behalten")
    args = ap.parse_args()

    cfg = load_config()
    if args.channel not in cfg["channels"]:
        raise SystemExit(f"Unbekannter Kanal '{args.channel}'. Verfügbar: {', '.join(cfg['channels'])}")
    ch = cfg["channels"][args.channel]

    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(2**31)
    rnd = random.Random(seed)
    if args.minutes:
        seconds = int(args.minutes * 60)
        hours = round(args.minutes / 60, 2)
    else:
        hours = args.hours or rnd.choice(ch["durations_hours"])
        seconds = int(hours * 3600)

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    work = OUTPUT / f"{args.channel}_{stamp}"
    print(f"▶ {ch['name']}: {hours:g} h, Seed {seed}")

    yt = None
    if not args.dry_run:            # Zugang zuerst prüfen – nicht erst nach Stunden Rendern scheitern
        import upload  # erst hier, damit Testläufe ohne Google-Bibliotheken gehen
        token = os.environ.get(ch["token_secret"])
        if not token:
            raise SystemExit(f"Secret {ch['token_secret']} fehlt.")
        yt = upload.service(token)
        upload.check_channel(yt, ch)
        print("  ✓ YouTube-Zugang ok")
        if os.environ.get("FORCE_UPLOAD") != "1" and upload.uploaded_today(args.channel):
            print("  ⏭ Heute wurde auf diesem Kanal schon hochgeladen – übersprungen (kein Doppel-Upload).")
            return

    info = render.render(ch, seconds, work, rnd)
    if yt:
        yt = upload.service(token)          # frische Verbindung nach dem langen Rendern
    recent = upload.recent_titles(yt) if yt else set()
    meta = metadata.build(ch, cfg, info, hours, rnd) if not yt else upload.unique_title(
        lambda: metadata.build(ch, cfg, info, hours, rnd), recent, rnd,
                               ["| Deep Sleep", "| Relax & Unwind", "| Study & Focus", "| Calm Night",
                                "| Peaceful Ambience", "| Sleep Better Tonight"])
    loop = ASSETS / ch["key"] / "video" / info["loop"]
    thumb = thumbnail.make(loop, work / "thumbnail.jpg", hours, meta["scene"], rnd)
    publish_at = next_publish_time(ch["publish_time_utc"], args.publish_days)

    record = {"channel": args.channel, "seed": seed, "hours": hours, "publish_at": publish_at,
              **meta, **info, "thumbnail": str(thumb)}
    print(f"  Titel: {meta['title']}")
    print(f"  Ebenen: {', '.join(l['file'] + ' (' + str(l['gain_db']) + ' dB)' for l in info['layers'])}")

    if args.dry_run:
        print("  (Testlauf – kein Upload)")
    else:
        import upload
        vid = upload.upload(yt, info["video_file"], meta, ch, publish_at)
        upload.set_thumbnail(yt, vid, thumb)
        PL = {"regen": ("Rain Sounds for Sleep", "Rain sounds for deep sleep, study and relaxation – new videos daily."),
              "kamin": ("Fireplace Sounds", "Crackling fireplace ambience for sleep, reading and cozy evenings."),
              "wasserfall": ("Water & Waterfall Sounds", "Waterfalls, streams and rivers for sleep, focus and calm.")}
        try:
            pid = ch.get("playlist_id") or upload.ensure_playlist(yt, args.channel, *PL.get(args.channel, (ch["name"], "")))
            upload.add_to_playlist(yt, vid, pid)
        except Exception as e:  # noqa: BLE001
            pid = None
            print(f"  ⚠ Playlist: {e}")
        record["video_id"] = vid
        upload.mark_uploaded(args.channel)
        print(f"  ✓ Hochgeladen: https://youtu.be/{vid} (öffentlich ab {publish_at})")
        try:                                          # täglicher 40-s-Clip: YouTube-Short + (im Wechsel) Instagram
            import ig_clip
            clip = ig_clip.make(info["video_file"], work / "ig_clip.mp4", hours, meta["scene"], args.channel, rnd)
            smeta = upload.unique_title(lambda: ig_clip.short_meta(args.channel, hours, meta["scene"], rnd, meta["title"]),
                                        recent, rnd, ["🌙", "✨", "💤", "🎧"])
            svid = upload.upload(yt, clip, smeta, ch, publish_at)
            record["short_id"] = svid
            print(f"  ✓ Short: https://youtu.be/{svid}")
            order = ["regen", "kamin", "wasserfall"]
            if args.channel in order and dt.date.today().toordinal() % 3 == order.index(args.channel):
                import ig_queue
                ig_queue.add("calmhaven", clip, ig_clip.caption(args.channel, hours, meta["scene"], rnd))
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ Short/Instagram-Clip übersprungen: {e}")
        if not args.keep:
            os.remove(info["video_file"])

    (work / "audio.m4a").unlink(missing_ok=True)
    with open(work / "meta.json", "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    print(f"  Dateien: {work}")


if __name__ == "__main__":
    main()
