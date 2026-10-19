"""
Komponiert eigene Spieluhr-Melodien (Schlaflieder) und synthetisiert sie.
Jede Melodie ist neu: Tonart, Tempo, Takt, Akkordfolge und Melodie werden zufällig,
aber nach Harmonieregeln gewählt -> ruhig, wohlklingend, kein fremdes Material.
"""
import numpy as np
from scipy import signal

SR = 44100

MAJOR = [0, 2, 4, 5, 7, 9, 11]
# Akkorde als Stufen der Dur-Tonleiter (0 = I, 3 = IV, 4 = V, 5 = vi, 1 = ii)
PROGRESSIONS = [
    [0, 5, 3, 4], [0, 3, 0, 4], [0, 4, 5, 3], [0, 3, 4, 0],
    [0, 5, 1, 4], [5, 3, 0, 4], [0, 0, 3, 4],
]
RHYTHMS_3 = [[1, 1, 1], [2, 1], [1, 2], [3], [1.5, 0.5, 1]]
RHYTHMS_4 = [[1, 1, 1, 1], [2, 1, 1], [1, 1, 2], [2, 2], [1.5, 0.5, 2], [4]]


def midi_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def chord_tones(root_midi, degree):
    """Dreiklang auf einer Tonleiterstufe -> Liste von MIDI-Tönen."""
    return [root_midi + MAJOR[(degree + k) % 7] + 12 * ((degree + k) // 7) for k in (0, 2, 4)]


def scale_tones(root_midi, lo, hi):
    out = []
    for octave in range(-2, 4):
        for s in MAJOR:
            m = root_midi + s + 12 * octave
            if lo <= m <= hi:
                out.append(m)
    return sorted(out)


def compose(rng, bars=16, bpm_range=(52, 68)):
    """Gibt (Noten der Melodie, Noten der Begleitung, Sekunden pro Schlag) zurück."""
    root = int(rng.choice([60, 62, 65, 67, 69]))          # C, D, F, G, A
    beats = int(rng.choice([3, 4]))
    bpm = rng.uniform(*bpm_range)
    spb = 60 / bpm
    prog = PROGRESSIONS[rng.integers(len(PROGRESSIONS))]
    prog_b = PROGRESSIONS[rng.integers(len(PROGRESSIONS))]
    rhythms = RHYTHMS_3 if beats == 3 else RHYTHMS_4
    mel_range = scale_tones(root, root + 2, root + 19)

    def phrase(progression, cadence_end):
        notes, prev = [], root + 12
        for bar, degree in enumerate(progression * 2):
            chord = chord_tones(root, degree)
            chord_set = {c % 12 for c in chord}
            rhythm = rhythms[rng.integers(len(rhythms))]
            if bar == len(progression) * 2 - 1:
                rhythm = [beats]                            # Phrase endet mit langem Ton
            for i, dur in enumerate(rhythm):
                strong = i == 0
                cands = [m for m in mel_range if abs(m - prev) <= (5 if strong else 3)]
                if strong:
                    cands = [m for m in cands if m % 12 in chord_set] or cands
                if bar == len(progression) * 2 - 1:
                    cands = [m for m in mel_range if m % 12 == (root if cadence_end else chord[1]) % 12] or cands
                    cands = sorted(cands, key=lambda m: abs(m - prev))[:1]
                weights = np.array([{0: 0.35, 1: 1.0, 2: 1.0, 3: 0.75, 4: 0.75}.get(abs(m - prev), 0.4) for m in cands])
                prev = int(rng.choice(cands, p=weights / weights.sum()))
                notes.append((prev, dur))
        return notes

    a = phrase(prog, cadence_end=False)
    a2 = phrase(prog, cadence_end=True)
    b = phrase(prog_b, cadence_end=False)
    melody = a + a2 + b + a2                                # Form A A' B A'

    # Begleitung: Arpeggio (gebrochener Akkord) eine Oktave tiefer
    accomp = []
    for section in (prog, prog, prog_b, prog):
        for degree in section * 2:
            chord = [c - 12 for c in chord_tones(root, degree)]
            pattern = [chord[0], chord[2], chord[1]] if beats == 3 else [chord[0], chord[2], chord[1], chord[2]]
            accomp += [(m, 1) for m in pattern]
    return melody, accomp, spb


def music_box_note(freq, dur, rng, vel=1.0):
    """Klang einer Spieluhr-Zunge: Grundton + typische unharmonische Obertöne, schnell abklingend."""
    length = int(SR * max(dur, 2.2))
    t = np.arange(length) / SR
    partials = [(1.0, 1.0, 2.2), (2.0, 0.18, 1.2), (5.93, 0.10, 0.35), (13.5, 0.03, 0.12)]
    tone = np.zeros(length)
    for ratio, amp, decay in partials:
        f = freq * ratio * (1 + rng.normal(0, 0.0008))
        if f < SR / 2.2:
            tone += amp * np.sin(2 * np.pi * f * t + rng.uniform(0, 6.28)) * np.exp(-t / decay)
    attack = np.minimum(1, t / 0.004)
    return tone * attack * vel


def render_piece(rng, melody, accomp, spb):
    total = sum(d for _, d in melody) * spb + 4
    out = np.zeros((int(total * SR), 2))

    def add(notes, vel, pan, oct_shift=0):
        pos = 0.0
        for m, d in notes:
            s = music_box_note(midi_hz(m + oct_shift), d * spb, rng, vel * rng.uniform(0.85, 1.0))
            i = int(pos * SR)
            e = min(len(out), i + len(s))
            out[i:e, 0] += s[: e - i] * (1 - pan)
            out[i:e, 1] += s[: e - i] * pan
            pos += d * spb + rng.normal(0, 0.006)            # minimal "menschliche" Ungenauigkeit

    add(melody, 0.55, 0.45)
    add(accomp, 0.22, 0.58)
    return out


def reverb(x, rng, seconds=2.6, wet=0.32):
    n = int(seconds * SR)
    ir = rng.standard_normal((n, 2)) * np.exp(-np.arange(n) / (SR * seconds / 6))[:, None]
    sos = signal.butter(2, 5000, "low", fs=SR, output="sos")
    ir = signal.sosfilt(sos, ir, axis=0)
    ir /= np.sqrt((ir ** 2).sum(axis=0))
    out = np.stack([signal.fftconvolve(x[:, c], ir[:, c])[: len(x)] for c in range(2)], axis=1)
    return x * (1 - wet) + out * wet


def lullaby(seed, repeats=2, bpm=(52, 68)):
    """Ein komplettes Schlaflied (Thema + leicht variierte Wiederholung), ca. 1,5–3 Minuten."""
    rng = np.random.default_rng(seed)
    melody, accomp, spb = compose(rng, bpm_range=bpm)
    parts = [render_piece(rng, melody, accomp, spb)]
    for _ in range(repeats - 1):
        spb2 = spb * rng.uniform(1.0, 1.06)                    # Wiederholung etwas langsamer
        parts.append(render_piece(rng, melody, accomp, spb2))
    y = np.concatenate(parts)
    y = reverb(y, rng)
    fade = int(3 * SR)
    y[-fade:] *= np.linspace(1, 0, fade)[:, None]
    return y / (np.max(np.abs(y)) + 1e-9) * 0.8
