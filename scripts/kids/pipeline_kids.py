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
    ap.add_argument("--format", default="long", choices=["long", "short"], help="nur für lernen")
    ap.add_argument("--topic", choices=["zahlen", "farben", "formen"], help="nur für lernen")
    ap.add_argument("--hours", type=float, help="nur für schlaf")
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

    thumb = None
    if args.channel == "schlaf":
        import schlaf
        if args.minutes:
            hours, seconds = round(args.minutes / 60, 2), int(args.minutes * 60)
        else:
            hours = args.hours or rnd.choice(ch["durations_hours"])
            seconds = int(hours * 3600)
        info = schlaf.produce(ch, seconds, work, rnd)
        meta = schlaf.metadata(ch, info, hours, rnd)
        thumb = make_thumb(info["loop"], work / "thumbnail.jpg", meta["thumb_label"], meta["thumb_sub"], at=0.2)
    elif args.channel == "lernen":
        import learn
        topic = args.topic or rnd.choice(ch["topics"])
        short = args.format == "short"
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

    print(f"  Titel: {meta['title']}")
    record = {"channel": args.channel, "seed": seed, **{k: v for k, v in info.items() if k != "script"}, **meta}

    if args.dry_run:
        print("  (Testlauf – kein Upload)")
    else:
        import upload
        token = os.environ.get(ch["token_secret"])
        if not token:
            raise SystemExit(f"Secret {ch['token_secret']} fehlt.")
        yt = upload.service(token)
        vid = upload.upload(yt, info["video_file"], meta, ch, publish_at=None)
        if thumb:
            upload.set_thumbnail(yt, vid, thumb)
        upload.add_to_playlist(yt, vid, ch.get("playlist_id"))
        record["video_id"] = vid
        print(f"  ✓ Privat hochgeladen: https://youtu.be/{vid} – bitte in YouTube Studio prüfen & veröffentlichen")
        if args.channel == "geschichten":
            stories.mark_used(info["story"]["title"])
        os.remove(info["video_file"])

    (work / "meta.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Dateien: {work}")


if __name__ == "__main__":
    main()
