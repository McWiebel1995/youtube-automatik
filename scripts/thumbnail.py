"""Erstellt ein Vorschaubild (1280x720) aus einem Frame des Video-Loops."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from common import ffmpeg

FONT_CANDIDATES = [
    Path(__file__).resolve().parent.parent / "assets" / "fonts" / "Thumbnail.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
]


def font(size):
    for p in FONT_CANDIDATES:
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size)


def make(loop_video, out_path: Path, hours, scene, rnd):
    frame = out_path.with_suffix(".frame.png")
    ffmpeg("-ss", round(rnd.uniform(1, 8), 2), "-i", loop_video, "-frames:v", "1", frame)
    img = Image.open(frame).convert("RGB").resize((1280, 720), Image.LANCZOS)
    img = ImageEnhance.Brightness(img).enhance(1.25)
    img = ImageEnhance.Contrast(img).enhance(1.15)

    # dunkler Verlauf unten für Lesbarkeit
    shade = Image.new("L", (1280, 720), 0)
    d = ImageDraw.Draw(shade)
    for y in range(360, 720):
        d.line([(0, y), (1280, y)], fill=int(200 * (y - 360) / 360))
    img = Image.composite(Image.new("RGB", img.size, (0, 0, 0)), img, shade)

    draw = ImageDraw.Draw(img)
    label = "1 HOUR" if hours == 1 else f"{hours:g} HOURS"
    size = 150
    while size > 60 and ImageDraw.Draw(img).textlength(label, font=font(size)) > 1160:
        size -= 6
    big, small = font(size), font(52)
    x, y = 60, 720 - 60 - 52 - 20 - size

    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).text((x, y), label, font=big, fill=(0, 0, 0, 220))
    img.paste(glow.filter(ImageFilter.GaussianBlur(10)), (0, 0), glow.filter(ImageFilter.GaussianBlur(10)))
    draw.text((x, y), label, font=big, fill=(255, 255, 255))
    draw.text((x + 6, 720 - 60 - 52), scene.upper(), font=small, fill=(235, 225, 200))

    img.save(out_path, quality=90)
    frame.unlink(missing_ok=True)
    return out_path
