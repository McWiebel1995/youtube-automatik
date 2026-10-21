#!/usr/bin/env python3
"""
Produziert ein Kinder-Video und lädt es PRIVAT hoch (Freigabe durch dich in YouTube Studio).

    python scripts/kids/pipeline_kids.py --channel schlaf --dry-run --minutes 3
    python scripts/kids/pipeline_kids.py --channel lernen --format short --topic farben --dry-run
    python scripts/kids/pipeline_kids.py --channel lernen --format long --dry-run
    python scripts/kids/pipeline_kids.py --channel geschichten --dry-run
"""
import argparse
import datetime as dt
import json
import os
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]

import yaml  # noqa: E402
from PIL import Image, ImageDraw, ImageEnhance  # noqa: E402

from common import OUTPUT, ROOT, ffmpeg  # noqa: E402
import drawing as dr  # noqa: E402


def load_cfg():
    cfg = yaml.safe_load((ROOT / "config" / "kids.yaml").read_text(encoding="utf-8"))
    for key, ch in cfg["channels"].items():
        ch["key"] = key
        for k, v in cfg.get("defaults", {}).items():
            ch.setdefault(k, v)
    return cfg


IG_ACCOUNT = {"schlaf": "mondmelodie", "lernen": "lernbaerchen", "geschichten": "gutenacht"}
IG_TAGS = {
    "schlaf": "#einschlafmusik #spieluhr #babyschlaf #schlaflied #gutenacht #babyeinschlafen #mamaleben #elternalltag",
    "lernen": "#lernenmitkindern #kleinkind #farbenlernen #zahlenlernen #montessorizuhause #kitaideen #mamaleben #elternalltag",
    "geschichten": "#gutenachtgeschichte #einschlafgeschichte #vorlesen #kindergeschichten #abendritual #mamaleben #elternalltag",
}


def ig_caption(channel, meta, info):
    """Instagram-Text: an Eltern gerichtet (Instagram ist erst ab 13)."""
    t = meta["title"].replace("#shorts", "").strip()
    if channel == "schlaf":
        body = (f"{info.get('title_word', 'Gute Nacht')} 🌙\nWenn dein Baby abends nicht zur Ruhe kommt: Eine sanfte "
                "Spieluhr-Melodie hilft beim Runterkommen. Jeden Tag ein neues, selbst komponiertes Schlaflied.\n\n"
                "💤 Speichern für heute Abend\n🎵 15 Minuten Einschlafmusik auf unserem YouTube-Kanal (Link in der Bio)")
    elif channel == "lernen":
        body = (f"{t}\nKleine Lernmomente für zwischendurch: Schau es gemeinsam mit deinem Kind an und sprecht laut mit. "
                "Wiederholung macht Kleinkinder sicher! 🐻\n\n📚 Das große Lernvideo (Zahlen, Farben & Formen) findest "
                "du auf unserem YouTube-Kanal (Link in der Bio)")
    else:
        body = (f"{info.get('title', t)} ✨\nEine Mini-Gute-Nacht-Geschichte für euer Abendritual. Kuscheln, zuhören, "
                "einschlafen. 🌙\n\n📖 Die ganze Geschichte (ca. 10 Minuten) hörst du auf unserem YouTube-Kanal "
                "(Link in der Bio)")
    return f"{body}\n\n{IG_TAGS[channel]}"


def make_thumb(video, out, big, small, at=0.35):
    from common import duration
    ffmpeg("-ss", f"{duration(video) * at:.2f}", "-i", video, "-frames:v", "1", out.with_suffix(".png"))
    img = Image.open(out.with_suffix(".png")).convert("RGB").resize((1280, 720), Image.LANCZOS)
    img = ImageEnhance.Brightness(img).enhance(1.1)
    d = ImageDraw.Draw(img)
    size = 120
    while size > 50 and d.textlength(big, font=dr.font(size)) > 1100:
        size -= 6
    dr.label(d, big, 640, 560, size, color=(90, 60, 140))
    if small:
        dr.label(d, small, 640, 90, 48, color=(90, 60, 140), box=(255, 236, 160))
    img.save(out, quality=90)
    out.with_suffix(".png").unlink(missing_ok=True)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--channel", required=True, choices=["schlaf", "lernen", "geschichten"])
    ap.add_argument("--format", default="both", choices=["long", "short", "both", "mix"],
                    help="nur für lernen: both = großes Lernvideo (~14 Min.) + Short")
    ap.add_argument("--topic", choices=["zahlen", "farben", "formen"], help="nur für lernen")
    ap.add_argument("--minutes", type=float, help="nur für schlaf (Tests)")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = load_cfg()
    ch = cfg["channels"][args.channel]
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(2**31)
    rnd = random.Random(seed)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    work = OUTPUT / f"kids-{args.channel}_{stamp}"
    print(f"▶ {ch['name']} (Seed {seed})")

    yt = None
    if not args.dry_run:            # Zugang zuerst prüfen
        import upload
        token = os.environ.get(ch["token_secret"])
        if not token:
            raise SystemExit(f"Secret {ch['token_secret']} fehlt.")
        yt = upload.service(token)
        upload.check_channel(yt, ch)
        print("  ✓ YouTube-Zugang ok")
        if os.environ.get("FORCE_UPLOAD") != "1" and upload.uploaded_recently(yt):
            print("  ⏭ Heute wurde auf diesem Kanal schon hochgeladen – übersprungen (kein Doppel-Upload).")
            return

    thumb = None
    extra = []                       # weitere Uploads in diesem Lauf (z. B. der tägliche Short)
    if args.channel == "schlaf":
        import shorts
        import schlaf
        minutes = args.minutes or ch.get("minutes", 14)
        seconds = int(minutes * 60)
        info = schlaf.produce(ch, seconds, work, rnd)
        meta = schlaf.metadata(ch, info, minutes, rnd)
        thumb = make_thumb(info["loop"], work / "thumbnail.jpg", meta["thumb_label"], meta["thumb_sub"], at=0.2)
        sinfo = shorts.schlaf_short(work / "short", rnd, float(ch.get("short_seconds", 45)))
        extra.append((sinfo, schlaf.short_metadata(ch, sinfo, rnd)))
    elif args.channel == "lernen":
        import learn
        fmt = args.format
        if fmt in ("both", "mix"):
            info = learn.produce(ch, "mix", False, work, rnd, ch["voice"], ch["speech_rate"])
            meta = learn.metadata(ch, info, rnd)
            thumb = make_thumb(info["video_file"], work / "thumbnail.jpg", "LERNEN MIT SPASS", "ZAHLEN · FARBEN · FORMEN", at=0.3)
            if fmt == "both":
                st = args.topic or rnd.choice(ch["topics"])
                sinfo = learn.produce(ch, st, True, work / "short", rnd, ch["voice"], ch["speech_rate"])
                extra.append((sinfo, learn.metadata(ch, sinfo, rnd)))
        else:
            topic = args.topic or rnd.choice(ch["topics"])
            short = fmt == "short"
            info = learn.produce(ch, topic, short, work, rnd, ch["voice"], ch["speech_rate"])
            meta = learn.metadata(ch, info, rnd)
            if not short:
                big = {"zahlen": "ZÄHLEN LERNEN", "farben": "FARBEN LERNEN", "formen": "FORMEN LERNEN"}[topic]
                thumb = make_thumb(info["video_file"], work / "thumbnail.jpg", big, None, at=0.3)
    else:
        import stories
        info = stories.produce(ch, work, rnd, ch["voice"], ch["speech_rate"])
        meta = stories.metadata(ch, info, rnd)
        thumb = make_thumb(info["loop"], work / "thumbnail.jpg", info["story"]["title"], "GUTE NACHT", at=0.3)
        import shorts
        st = info["story"]
        sinfo = shorts.story_short(st["title"], stories.mini_of(st), work / "short", rnd, ch["voice"], ch["speech_rate"])
        stitle = rnd.choice(ch["short_titles"]).format(title=st["title"])[:100]
        sdesc = (f"🌙 {st['title']} – eine Mini-Gute-Nacht-Geschichte.\n\nDie ganze Geschichte (ca. "
                 f"{max(1, round(info['seconds'] / 60))} Minuten) hörst du auf unserem Kanal.\n\n"
                 "#shorts #GuteNachtGeschichte #Einschlafgeschichte")
        extra.append((sinfo, {"title": stitle, "description": sdesc, "tags": ch["tags"] + ["shorts"]}))

    print(f"  Titel: {meta['title']}")
    record = {"channel": args.channel, "seed": seed, **{k: v for k, v in info.items() if k != "script"}, **meta}

    if args.dry_run:
        print("  (Testlauf – kein Upload)")
        for xinfo, xmeta in extra:
            print(f"  + Short: {xmeta['title']} ({xinfo['video_file']})")
    else:
        import upload
        vid = upload.upload(yt, info["video_file"], meta, ch, publish_at=None)
        if thumb:
            upload.set_thumbnail(yt, vid, thumb)
        upload.add_to_playlist(yt, vid, ch.get("playlist_id"))
        record["video_id"] = vid
        print(f"  ✓ Privat hochgeladen: https://youtu.be/{vid} – bitte in YouTube Studio prüfen & veröffentlichen")
        if args.channel == "geschichten":
            stories.mark_used(info["story"]["title"])
        os.remove(info["video_file"])
        for xinfo, xmeta in extra:
            xvid = upload.upload(yt, xinfo["video_file"], xmeta, ch, publish_at=None)
            record.setdefault("extra_uploads", []).append({"video_id": xvid, "title": xmeta["title"]})
            print(f"  ✓ Short privat hochgeladen: https://youtu.be/{xvid}")
            import ig_queue                                   # Short auch als Instagram-Reel (abends)
            ig_queue.add(IG_ACCOUNT[args.channel], xinfo["video_file"], ig_caption(args.channel, xmeta, xinfo))

    (work / "meta.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Dateien: {work}")


if __name__ == "__main__":
    main()
