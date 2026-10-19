"""Builds title, description and tags (English) – slightly different every time."""

LAYER_NAMES = {
    "rain_": "gentle rain", "roof_": "rain on the roof", "thunder_": "distant thunder",
    "wind_": "soft wind", "fire_": "crackling fireplace", "clock_": "a quietly ticking clock",
    "waterfall_": "waterfall", "stream_": "babbling stream", "birds_": "birdsong",
}

INTROS = [
    "Lean back and let the day fade away.",
    "Perfect for sleeping, studying, reading or simply switching off.",
    "A calm soundscape for deep sleep and full focus.",
    "Close your eyes, breathe slowly – you have arrived.",
    "Let these soothing sounds wash away stress and help you drift off.",
]

USES = [
    "😴 Falling asleep & sleeping through the night", "📚 Studying & concentration",
    "🧘 Meditation & yoga", "👶 Calming babies", "💻 Work & focus", "📖 Reading & relaxing",
    "🎧 Masking tinnitus", "✈️ Travel & noisy environments",
]


def build(channel, cfg, render_info, hours, rnd):
    scene = render_info.get("loop_scene") or rnd.choice(channel["scenes"])
    extras = render_info["layers"][1:]
    extra_title = cfg.get("extra_titles", {}).get(extras[0]["prefix"], "") if extras else ""
    hours_txt = f"{hours:g}"

    title = rnd.choice(channel["title_templates"]).format(
        scene=scene, hours=hours_txt, extra_title=extra_title)
    if hours == 1:
        title = title.replace("1 Hours", "1 Hour")
    title = title[:100]

    sounds = [LAYER_NAMES.get(l["prefix"], l["prefix"]) for l in render_info["layers"]]
    uses = rnd.sample(USES, 4)
    hour_word = "hour" if hours == 1 else "hours"
    desc = "\n".join([
        f"{scene} – {hours_txt} {hour_word} of {', '.join(sounds)}.",
        "",
        rnd.choice(INTROS),
        "",
        "In this mix you'll hear:",
        *[f"• {s}" for s in sounds],
        "",
        "Perfect for:",
        *uses,
        "",
        "All sounds in this video were created and mixed by us – every video is a unique mix.",
        "",
        "🔔 Subscribe for new soundscapes every week.",
        "",
        " ".join("#" + t.replace(" ", "") for t in channel["tags"][:3]),
    ])

    tags = list(dict.fromkeys(channel["tags"] + [scene.lower()] + sounds))
    while sum(len(t) + 1 for t in tags) > 480:   # YouTube allows max. 500 characters of tags
        tags.pop()

    return {"title": title, "description": desc[:4900], "tags": tags, "scene": scene}
