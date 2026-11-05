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
ALL 3 questions must clearly belong to the theme – a viewer must instantly see why each question fits the title.
The title must name exactly what the questions are about (if the questions are about oceans, the title says oceans;
never promise a topic the questions don't cover). Prefer ONE narrow topic over a broad mix.
Avoid these questions already used: {used}
Answer ONLY JSON: {{"hook": "max 8 words, e.g. 'Only 1% get all 3 right!'", "title": "max 80 chars incl #shorts, names the exact topic",
 "questions": [{{"q": "...", "options": ["...", "...", "..."], "correct": 0, "explain": "...", "wiki": "Wikipedia article title to verify"}}]}}"""
THEMES = [
    # bisher
    "space and planets", "the human body", "animals", "oceans and sea life", "physics in everyday life",
    "dinosaurs", "inventions", "the Moon", "black holes and stars", "weather and climate", "the brain",
    # neu zum Testen (Publikum: vor allem USA, viele über 55)
    "US geography and national parks", "world geography and capitals", "famous landmarks", "ancient civilizations",
    "ancient Rome and its engineering", "ancient Egypt and the pyramids", "volcanoes and earthquakes", "the deep sea", "birds", "insects", "trees and plants", "the solar system",
    "astronauts and space missions", "science in the kitchen", "the five senses", "rivers and mountains",
    "mammals", "sea creatures", "electricity and energy", "famous scientists", "everyday chemistry", "the Arctic and Antarctica",
]
THEME_STATS = ROOT / "data" / "quiz_themes.json"     # wird montags aus den Analytics berechnet (quiz_learn.py)
QUIZ_LOG = ROOT / "data" / "quiz_log.json"


def pick_theme(rnd):
    """Lernende Auswahl: neue Themen zuerst je 2x testen, danach meist die besten, aber immer etwas Neues."""
    stats = json.loads(THEME_STATS.read_text()) if THEME_STATS.exists() else {}
    log = json.loads(QUIZ_LOG.read_text()) if QUIZ_LOG.exists() else []
    recent = [x["theme"] for x in log[-3:]]
    pool = [t for t in THEMES if t not in recent] or THEMES
    tested = {t: s for t, s in stats.items() if s.get("n", 0) >= 1 and t in pool}
    untested = [t for t in pool if stats.get(t, {}).get("n", 0) + sum(1 for x in log[-20:] if x["theme"] == t) < 2]
    r = rnd.random()
    if untested and (r < 0.25 or not tested):        # ~1 von 4 Quiz testet ein neues Thema
        return rnd.choice(untested), "Test"
    if tested and r < 0.85:
        top = sorted(tested, key=lambda t: -tested[t]["score"])[:5]
        weights = [max(0.1, tested[t]["score"]) for t in top]
        return rnd.choices(top, weights=weights)[0], "Gewinner"
    return rnd.choice(pool), "Zufall"


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
    theme, why, asked = None, "", []
    try:                                              # Zuschauerwünsche aus den Kommentaren (topic_requests.py)
        import topic_requests
        top = topic_requests.top_open(topic_requests.collect())
        if top and rnd.random() < 0.4:
            theme, why, asked = top["topic"], f"Zuschauerwunsch ({top['count']}x)", top["users"][:2]
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ Themenwünsche: {str(e)[:120]}")
    if not theme:
        theme, why = pick_theme(rnd)
    print(f"  Thema: {theme} ({why})")
    qz = gemini.ask_json(QUIZ_TASK.format(theme=theme, used="; ".join(used[-80:]) or "none"), temperature=0.9)
    facts = []
    for q in qz["questions"][:3]:
        for t, x, _ in wi.wikipedia(q.get("wiki") or q["q"], 1):
            facts.append(f"[{t}] {x[:900]}")
    if facts:                                            # Faktencheck
        qz = gemini.ask_json("Verify this quiz against the facts. If an answer is wrong or doubtful, replace that "
                             "question with a correct one. Also check that the title matches ALL questions exactly – "
                             "if a question does not fit the title, replace the question (or make the title match all "
                             "three). Keep the exact JSON format.\nFacts:\n" + "\n".join(facts) +
                             "\n\nQuiz JSON:\n" + json.dumps(qz, ensure_ascii=False), temperature=0.2)
    qz["theme"] = theme
    qz["asked_by"] = asked
    log = json.loads(QUIZ_LOG.read_text()) if QUIZ_LOG.exists() else []
    qz["episode"] = len(log) + 1
    if asked:                                         # "You asked for it!" – Wunsch sichtbar machen
        qz["hook"] = f"You asked for it: {theme}!"
        t = re.sub(r"(?i)#shorts", "", qz["title"]).strip()
        qz["title"] = f"You Asked For It: {t}"[:90] + " #shorts"
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


LEVEL = [("EASY", (46, 204, 113)), ("MEDIUM", (255, 176, 59)), ("HARD", (255, 92, 92))]


def header(d, episode):
    if episode:
        d.text((W / 2, 95), f"BEYOND THE IF  ·  QUIZ #{episode}", font=font(40), fill=(255, 255, 255, 170), anchor="mm")


def score_dots(d, done):
    """Punktestand zum Mitzählen (oben – unten verdeckt die Shorts-Oberfläche): aufgedeckte Fragen gefüllt."""
    d.text((W / 2 - 70, 170), "KEEP SCORE", font=font(36), fill=(255, 255, 255, 190), anchor="rm")
    for k in range(3):
        x = W / 2 - 20 + k * 62
        col = (255, 210, 90, 255) if k < done else (255, 255, 255, 60)
        d.ellipse((x - 20, 150, x + 20, 190), fill=col)


def frame(bg, q, idx, state, t_count, hook=None, episode=None):
    """state: 'hook' | 'ask' | 'count' | 'reveal' | 'outro'"""
    im = bg.copy()
    d = ImageDraw.Draw(im, "RGBA")
    header(d, episode)
    if state == "hook":
        f = font(96)
        lines = wrap(d, hook, f, W - 160)
        y = H // 2 - len(lines) * 60 - 60
        for ln in lines:
            d.text((W / 2, y), ln, font=f, fill="white", anchor="mm")
            y += 120
        d.text((W / 2, y + 80), "Question 3 is the hardest...", font=font(56, bold=False), fill=(255, 210, 90), anchor="mm")
        score_dots(d, 0)
        return im
    if state == "outro":
        f = font(88)
        y = H // 2 - 260
        for ln in wrap(d, "Got 3/3?", f, W - 160) + wrap(d, "Comment 3/3!", f, W - 160):
            d.text((W / 2, y), ln, font=f, fill="white", anchor="mm")
            y += 115
        y += 90
        for ln in wrap(d, "Next quiz topic? Comment it below and I'll make it!", font(58, bold=False), W - 200):
            d.text((W / 2, y), ln, font=font(58, bold=False), fill=(255, 210, 90), anchor="mm")
            y += 78
        score_dots(d, 3)
        return im
    lvl, lcol = LEVEL[min(idx, 2)]
    d.text((W / 2 - 40, 262), f"QUESTION {idx + 1}/3", font=font(52), fill=(255, 210, 90), anchor="rm")
    card(d, (W / 2 - 10, 232, W / 2 + 40 + len(lvl) * 34, 292), lcol + (235,), radius=30)
    d.text((W / 2 + 15 + len(lvl) * 17, 262), lvl, font=font(38), fill="white", anchor="mm")
    score_dots(d, idx + (1 if state == "reveal" else 0))
    fq = font(72)
    lines = wrap(d, q["q"], fq, W - 180)
    card(d, (70, 320, W - 70, 380 + len(lines) * 92 + 60), (255, 255, 255, 235))
    y = 420
    for ln in lines:
        d.text((W / 2, y), ln, font=fq, fill=(25, 25, 45), anchor="mm")
        y += 92
    top = max(760, y + 110)
    end = top + 2 * 210 + 170
    for k, opt in enumerate(q["options"][:3]):
        y0 = top + k * 210
        fill, txtc, outline = (255, 255, 255, 40), "white", (255, 255, 255, 160)
        if state == "reveal":
            if k == q["correct"]:
                fill, outline, txtc = (46, 204, 113, 235), (255, 255, 255, 255), "white"
            else:
                fill, outline, txtc = (255, 255, 255, 18), (255, 255, 255, 60), (255, 255, 255, 110)
        card(d, (110, y0, W - 110, y0 + 170), fill, outline=outline)
        d.text((190, y0 + 85), "ABC"[k], font=font(76), fill=(255, 210, 90) if state != "reveal" else txtc, anchor="mm")
        d.text((W / 2 + 40, y0 + 85), opt, font=font(64, bold=False), fill=txtc, anchor="mm")
    if state == "count":
        left = max(0.0, COUNT - t_count)
        frac = left / COUNT
        card(d, (110, end + 210, W - 110, end + 260), (255, 255, 255, 50), radius=25)
        if frac > 0:
            card(d, (110, end + 210, 110 + (W - 220) * frac, end + 260), (255, 210, 90, 255), radius=25)
        d.text((W / 2, end + 120), str(int(np.ceil(left)) or 1), font=font(110), fill="white", anchor="mm")
    if state == "reveal":
        fe = font(48, bold=False)
        for j, ln in enumerate(wrap(d, q.get("explain", ""), fe, W - 200)[:3]):
            d.text((W / 2, end + 90 + j * 62), ln, font=fe, fill=(230, 230, 255), anchor="mm")
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
        a_hook = say(qz["hook"] + " Question three is the hardest. Keep score!", "hook")
        a_q = [say(f"{q['q']} A: {q['options'][0]}. B: {q['options'][1]}. Or C: {q['options'][2]}?", f"q{i}")
               for i, q in enumerate(qs)]
        a_r = [say(f"It's {'ABC'[q['correct']]}! {q['options'][q['correct']]}. {q.get('explain', '')}", f"r{i}")
               for i, q in enumerate(qs)]
        a_out = say("Got all three? Comment three out of three! And tell me the topic for my next quiz, I read every comment.", "out")
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
            cache[key] = np.asarray(frame(bg, q, i, state, tt - t0, qz["hook"], qz.get("episode")).convert("RGB")).tobytes()
        p.stdin.write(cache[key])
    p.stdin.close()
    p.wait()
    wi.ass([], work / "none.ass", W, H, 10, 0)
    wi.mix_and_render(work / "v.mp4", vo[: int(total * SR)], out / "quiz_short.mp4", work, work / "none.ass", music_db=-24)
    meta = {"title": qz["title"][:100], "theme": qz["theme"], "questions": qs,
            "episode": qz.get("episode"), "asked_by": qz.get("asked_by", []),
            "description": (f"Topic requested by {' & '.join(qz['asked_by'])} – thanks! 🙌\n\n" if qz.get("asked_by") else "") +
                           "Test yourself! " + " | ".join(q["q"] for q in qs) +
                           "\n\n✅ Every answer fact-checked with Wikipedia." +
                           "\n💬 Comment your score and the topic for the next quiz!" +
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
    log = json.loads(QUIZ_LOG.read_text()) if QUIZ_LOG.exists() else []
    import datetime as _dt
    log.append({"id": vid, "theme": meta["theme"], "title": meta["title"], "date": _dt.date.today().isoformat(),
                "episode": meta.get("episode"), "asked_by": meta.get("asked_by", [])})
    if meta.get("asked_by"):
        try:
            import topic_requests
            topic_requests.mark_used(meta["theme"])
        except Exception:  # noqa: BLE001
            pass
    QUIZ_LOG.write_text(json.dumps(log[-400:], ensure_ascii=False, indent=1), encoding="utf-8")
    used = json.loads(USED.read_text(encoding="utf-8")) if USED.exists() else []
    USED.write_text(json.dumps((used + [q["q"] for q in meta["questions"]])[-500:], ensure_ascii=False, indent=1),
                    encoding="utf-8")
    if os.environ.get("IG_TOKEN_WHATIF") or os.environ.get("IG_WHATIF_ALT"):
        import ig_queue
        cta = "💬 Comment QUIZ and I'll DM you 3 bonus questions!\n\n"   # -> ig_dm.py beantwortet automatisch
        ig_queue.add("whatif", out / "quiz_short.mp4", cta + meta["description"])
    upload.mark_uploaded(os.environ.get("QUIZ_LOCK", "whatif-quiz"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output/quiz")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not a.dry_run:
        import upload
        if os.environ.get("FORCE_UPLOAD") != "1" and upload.uploaded_today(os.environ.get("QUIZ_LOCK", "whatif-quiz")):
            print("Heute schon ein Quiz – übersprungen."); sys.exit(0)
        if not upload.quota_ok(wi.CFG["token_secret"]):
            sys.exit(0)
        import datetime as _dt
        if _dt.datetime.now(_dt.timezone.utc).weekday() == 4 and os.environ.get("FORCE_UPLOAD") != "1":
            print("⏸ Freitag: kein Quiz (Freitag = langes Video + 2 Shorts)."); sys.exit(0)
        if not upload.pace_ok(wi.CFG["token_secret"], label="Quiz"):
            sys.exit(0)
    m = build(Path(a.out))
    if not a.dry_run:
        upload_quiz(Path(a.out), m)
