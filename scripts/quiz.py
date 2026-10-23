#!/usr/bin/env python3
"""
Quiz-Shorts (Beyond the If): 3 Fragen mit je 3 Antworten, Countdown, dann wird die Lösung aufgedeckt.

  Fragen:  Gemini (Wissenschaft/Weltall/Natur/Geschichte), Faktencheck mit Wikipedia
  Stimme:  Chatterbox (Erzähler-Referenz), liest Frage, Antworten und Lösung
  Bild:    1080x1920, Fragekarte, 3 Antwortkarten (A/B/C), Countdown-Balken mit Ticken, Aufdecken in Grün

    python scripts/quiz.py --out output/quiz [--dry-run]
"""
import argparse
import json
import os
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from scipy.io import wavfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT / "anime")]
import gemini  # noqa: E402
import whatif as wi  # noqa: E402

W, H, FPS, SR = 1080, 1920, 30, wi.SR
COUNT = 5.0          # Sekunden Bedenkzeit
REVEAL = 3.2         # Sekunden Lösung
USED = ROOT / "data" / "quiz_used.json"

QUIZ_TASK = """Create a 3-question science quiz for a YouTube Short of the channel "Beyond the If".
Theme: {theme}. Difficulty rising: easy, medium, hard. Each question has exactly 3 answer options (A, B, C),
exactly one correct, plausible wrong options. Questions must be 100% factually correct, short (max 12 words),
options max 4 words. Add a one-sentence surprising explanation (max 14 words) for each.
Avoid these questions already used: {used}
Answer ONLY JSON: {{"hook": "max 8 words, e.g. 'Only 1% get all 3 right!'", "title": "max 80 chars incl #shorts",
 "questions": [{{"q": "...", "options": ["...", "...", "..."], "correct": 0, "explain": "...", "wiki": "Wikipedia article title to verify"}}]}}"""
THEMES = ["space and planets", "the human body", "animals", "Earth and oceans", "physics in everyday life",
          "dinosaurs", "inventions", "the Moon", "black holes and stars", "weather and climate", "the brain"]


def font(size, bold=True):
    p = ROOT / "assets" / "fonts" / "Montserrat.ttf"
    if p.exists():
        f = ImageFont.truetype(str(p), size)
        try:
            f.set_variation_by_name("ExtraBold" if bold else "SemiBold")
        except Exception:  # noqa: BLE001
            pass
        return f
    return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)


def wrap(d, text, f, maxw):
    words, lines, cur = text.split(), [], ""
    for w_ in words:
        t = (cur + " " + w_).strip()
        if d.textlength(t, font=f) > maxw and cur:
            lines.append(cur)
            cur = w_
        else:
            cur = t
    return lines + [cur] if cur else lines


# ----------------------------------------------------------------- Inhalt
def make_quiz(rnd):
    used = json.loads(USED.read_text(encoding="utf-8")) if USED.exists() else []
    theme = rnd.choice(THEMES)
    qz = gemini.ask_json(QUIZ_TASK.format(theme=theme, used="; ".join(used[-80:]) or "none"), temperature=0.9)
    facts = []
    for q in qz["questions"][:3]:
        for t, x, _ in wi.wikipedia(q.get("wiki") or q["q"], 1):
            facts.append(f"[{t}] {x[:900]}")
    if facts:                                            # Faktencheck
        qz = gemini.ask_json("Verify this quiz against the facts. If an answer is wrong or doubtful, replace that "
                             "question with a correct one. Keep the exact JSON format.\nFacts:\n" + "\n".join(facts) +
                             "\n\nQuiz JSON:\n" + json.dumps(qz, ensure_ascii=False), temperature=0.2)
    qz["theme"] = theme
    return qz


# ----------------------------------------------------------------- Bild
BG = [((14, 18, 48), (60, 24, 90)), ((8, 30, 50), (20, 90, 110)), ((30, 10, 40), (110, 40, 70)), ((10, 22, 30), (40, 80, 60))]


def background(rnd):
    top, bot = rnd.choice(BG)
    g = np.linspace(0, 1, H)[:, None, None]
    img = (np.array(top) * (1 - g) + np.array(bot) * g).repeat(W, axis=1).astype(np.uint8)
    base = Image.fromarray(img)
    d = ImageDraw.Draw(base)
    for _ in range(140):                                   # Sterne/Punkte für Tiefe
        x, y, r = rnd.uniform(0, W), rnd.uniform(0, H), rnd.choice([1, 1, 2, 3])
        d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, 120))
    return base.filter(ImageFilter.GaussianBlur(0.6))


def card(d, box, fill, radius=34, outline=None):
    d.rounded_rectangle(box, radius, fill=fill, outline=outline, width=6 if outline else 0)


def frame(bg, q, idx, state, t_count, hook=None):
    """state: 'hook' | 'ask' | 'count' | 'reveal' | 'outro'"""
    im = bg.copy()
    d = ImageDraw.Draw(im, "RGBA")
    if state in ("hook", "outro"):
        f = font(96)
        lines = wrap(d, hook, f, W - 160)
        y = H // 2 - len(lines) * 60
        for ln in lines:
            d.text((W / 2, y), ln, font=f, fill="white", anchor="mm")
            y += 120
        return im
    d.text((W / 2, 220), f"QUESTION {idx + 1}/3", font=font(54), fill=(255, 210, 90), anchor="mm")
    fq = font(72)
    lines = wrap(d, q["q"], fq, W - 180)
    card(d, (70, 320, W - 70, 380 + len(lines) * 92 + 60), (255, 255, 255, 235))
    y = 420
    for ln in lines:
        d.text((W / 2, y), ln, font=fq, fill=(25, 25, 45), anchor="mm")
        y += 92
    top = max(820, y + 140)
    for k, opt in enumerate(q["options"][:3]):
        y0 = top + k * 230
        fill, txtc, outline = (255, 255, 255, 40), "white", (255, 255, 255, 160)
        if state == "reveal":
            if k == q["correct"]:
                fill, outline, txtc = (46, 204, 113, 235), (255, 255, 255, 255), "white"
            else:
                fill, outline, txtc = (255, 255, 255, 18), (255, 255, 255, 60), (255, 255, 255, 110)
        card(d, (110, y0, W - 110, y0 + 180), fill, outline=outline)
        d.text((190, y0 + 90), "ABC"[k], font=font(76), fill=(255, 210, 90) if state != "reveal" else txtc, anchor="mm")
        d.text((W / 2 + 40, y0 + 90), opt, font=font(64, bold=False), fill=txtc, anchor="mm")
    if state == "count":
        left = max(0.0, COUNT - t_count)
        frac = left / COUNT
        card(d, (110, H - 300, W - 110, H - 250), (255, 255, 255, 50), radius=25)
        if frac > 0:
            card(d, (110, H - 300, 110 + (W - 220) * frac, H - 250), (255, 210, 90, 255), radius=25)
        d.text((W / 2, H - 380), str(int(np.ceil(left)) or 1), font=font(110), fill="white", anchor="mm")
    if state == "reveal":
        fe = font(48, bold=False)
        for j, ln in enumerate(wrap(d, q.get("explain", ""), fe, W - 200)[:3]):
            d.text((W / 2, H - 360 + j * 62), ln, font=fe, fill=(230, 230, 255), anchor="mm")
    return im


# ----------------------------------------------------------------- Ton
def tick():
    t = np.linspace(0, 0.05, int(0.05 * SR), False)
    return (np.sin(2 * np.pi * 1600 * t) * np.exp(-t * 90) * 0.35).astype(np.float32)


def ding():
    t = np.linspace(0, 0.7, int(0.7 * SR), False)
    return ((np.sin(2 * np.pi * 880 * t) + 0.6 * np.sin(2 * np.pi * 1320 * t)) * np.exp(-t * 5) * 0.25).astype(np.float32)


def build(out: Path, seed=None):
    rnd = random.Random(seed)
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=out))
    qz = make_quiz(rnd)
    qs = qz["questions"][:3]
    import modal
    from modal_app import Voice, app
    ref_path = ROOT / "data" / "voices" / "anime" / "narrator.wav"
    ref = ref_path.read_bytes() if ref_path.exists() else b""
    with modal.enable_output(), app.run():
        v = Voice()

        def say(text, tag):
            return wi.to_sr(v.speak.remote(text, ref, exaggeration=0.65, cfg_weight=0.45, seed=5), work, tag + ".wav")
        a_hook = say(qz["hook"], "hook")
        a_q = [say(f"{q['q']} A: {q['options'][0]}. B: {q['options'][1]}. Or C: {q['options'][2]}?", f"q{i}")
               for i, q in enumerate(qs)]
        a_r = [say(f"It's {'ABC'[q['correct']]}! {q['options'][q['correct']]}. {q.get('explain', '')}", f"r{i}")
               for i, q in enumerate(qs)]
        a_out = say("How many did you get right? Tell me in the comments, and follow for more!", "out")
    # Zeitplan
    timeline, t = [], 0.0
    timeline.append(("hook", None, 0, t, t + len(a_hook) / SR + 0.4, a_hook))
    t += len(a_hook) / SR + 0.4
    for i, q in enumerate(qs):
        d_ask = len(a_q[i]) / SR + 0.3
        timeline.append(("ask", q, i, t, t + d_ask, a_q[i]))
        t += d_ask
        timeline.append(("count", q, i, t, t + COUNT, None))
        t += COUNT
        d_rev = max(REVEAL, len(a_r[i]) / SR + 0.5)
        timeline.append(("reveal", q, i, t, t + d_rev, a_r[i]))
        t += d_rev
    timeline.append(("outro", None, 0, t, t + len(a_out) / SR + 0.6, a_out))
    total = t + len(a_out) / SR + 0.6
    # Audio
    vo = np.zeros(int((total + 1) * SR), np.float32)
    for state, q, i, t0, t1, a in timeline:
        s0 = int(t0 * SR)
        if a is not None:
            vo[s0:s0 + len(a)] += a[: len(vo) - s0]
        if state == "count":
            for k in range(int(COUNT)):
                p = s0 + int(k * SR)
                vo[p:p + len(tick())] += tick()
        if state == "reveal":
            vo[s0:s0 + len(ding())] += ding()
    # Bild
    bg = background(rnd)
    p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                          "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                          "-pix_fmt", "yuv420p", str(work / "v.mp4")], stdin=subprocess.PIPE)
    cache = {}
    for n in range(int(total * FPS)):
        tt = n / FPS
        seg = next((x for x in timeline if x[3] <= tt < x[4]), timeline[-1])
        state, q, i, t0 = seg[0], seg[1], seg[2], seg[3]
        key = (state, i) if state != "count" else (state, i, int((tt - t0) * 10))
        if key not in cache:
            cache.clear() if len(cache) > 50 else None
            hook = qz["hook"] if state == "hook" else "How many did you get right?"
            cache[key] = np.asarray(frame(bg, q, i, state, tt - t0, hook).convert("RGB")).tobytes()
        p.stdin.write(cache[key])
    p.stdin.close()
    p.wait()
    wi.ass([], work / "none.ass", W, H, 10, 0)
    wi.mix_and_render(work / "v.mp4", vo[: int(total * SR)], out / "quiz_short.mp4", work, work / "none.ass", music_db=-24)
    meta = {"title": qz["title"][:100], "theme": qz["theme"], "questions": qs,
            "description": "Test yourself! " + " | ".join(q["q"] for q in qs) +
                           "\n\nAnswers explained in the video.\n#shorts #quiz #science #trivia #beyondtheif",
            "tags": ["shorts", "quiz", "science quiz", "trivia", qz["theme"]]}
    (out / "quiz_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    subprocess.run(["rm", "-rf", str(work)])
    return meta


def upload_quiz(out: Path, meta):
    import upload
    yt = upload.service(os.environ[wi.CFG["token_secret"]])
    upload.check_channel(yt, wi.CFG)
    ch = {"category_id": "28", "made_for_kids": False, "privacy": "public", "name": wi.CFG["name"]}
    vid = upload.upload(yt, out / "quiz_short.mp4", meta, ch)
    print(f"  ✓ Quiz: https://youtu.be/{vid}")
    used = json.loads(USED.read_text(encoding="utf-8")) if USED.exists() else []
    USED.write_text(json.dumps((used + [q["q"] for q in meta["questions"]])[-500:], ensure_ascii=False, indent=1),
                    encoding="utf-8")
    if os.environ.get("IG_TOKEN_WHATIF"):
        import ig_queue
        ig_queue.add("whatif", out / "quiz_short.mp4", meta["description"])
    upload.mark_uploaded("whatif-quiz")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output/quiz")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not a.dry_run:
        import upload
        if os.environ.get("FORCE_UPLOAD") != "1" and upload.uploaded_today("whatif-quiz"):
            sys.exit("Heute schon ein Quiz – übersprungen.")
    m = build(Path(a.out))
    if not a.dry_run:
        upload_quiz(Path(a.out), m)
