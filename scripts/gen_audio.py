#!/usr/bin/env python3
"""
Erzeugt alle Natur-Sounds synthetisch (keine fremden Dateien, keine Lizenzen):
Regen, Dachregen, Donner, Wind, Kaminfeuer, Uhr-Ticken, Wasserfall, Bach, Vögel.

Jeder Sound ist ein nahtloser Loop (Standard 3 Minuten) und wird als FLAC gespeichert.
Mehrere Varianten pro Sound (unterschiedliche Seeds) sorgen für Abwechslung.

Beispiel:
    python scripts/gen_audio.py --variants 3 --seconds 180
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.io import wavfile

SR = 44100
ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"


# ----------------------------------------------------------------- Bausteine
def colored_noise(n, rng, exponent):
    """exponent 0 = weiß, 1 = rosa, 2 = braun (Leistungsspektrum ~ 1/f^exponent)."""
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / SR)
    f[0] = f[1]
    spec /= f ** (exponent / 2)
    x = np.fft.irfft(spec, n)
    return x / (np.std(x) + 1e-12)


def filt(x, kind, freq, order=4):
    sos = signal.butter(order, freq, btype=kind, fs=SR, output="sos")
    return signal.sosfilt(sos, x)


def lfo(n, rng, rate_hz, depth, base=1.0):
    """Langsame, zufällige Schwankung (geglättetes Rauschen)."""
    k = max(4, int(n / SR * rate_hz) + 4)
    pts = rng.standard_normal(k)
    curve = np.interp(np.linspace(0, k - 1, n), np.arange(k), pts)
    curve = filt(curve, "low", max(rate_hz, 0.05), order=2) if rate_hz < SR / 4 else curve
    curve /= np.max(np.abs(curve)) + 1e-12
    return base + depth * curve


def events(n, rng, rate, rate_curve=None):
    """Zufällige Ereignis-Zeitpunkte (Poisson), optional mit wechselnder Dichte."""
    if rate_curve is None:
        count = rng.poisson(rate * n / SR)
        return np.sort(rng.integers(0, n, count))
    prob = rate * rate_curve / SR
    return np.nonzero(rng.random(n) < np.clip(prob, 0, 1))[0]


def place(n, positions, amps, kernels, rng):
    """Legt kurze Klang-Bausteine (kernels) an die Ereignis-Positionen."""
    out = np.zeros(n + max(len(k) for k in kernels))
    choice = rng.integers(0, len(kernels), len(positions))
    for idx, kern in enumerate(kernels):
        sel = choice == idx
        imp = np.zeros(n)
        np.add.at(imp, positions[sel], amps[sel])
        conv = signal.fftconvolve(imp, kern)[: n]
        out[: n] += conv
    return out[:n]


def decay_kernel(rng, ms, f_lo, f_hi, tonal=0.0):
    length = int(SR * ms / 1000)
    t = np.arange(length) / SR
    env = np.exp(-t / (ms / 1000 / 4))
    noise = rng.standard_normal(length)
    lo, hi = sorted(rng.uniform(f_lo, f_hi, 2))
    hi = max(hi, lo * 1.3)
    noise = filt(noise, "band", [lo, min(hi, SR / 2 - 100)], order=2)
    tone = np.sin(2 * np.pi * rng.uniform(f_lo, f_hi) * t)
    k = (1 - tonal) * noise / (np.std(noise) + 1e-12) + tonal * tone
    return k * env


def stereo(make, n, rng, width=0.6):
    """Baut zwei teil-unabhängige Kanäle für räumlichen Klang."""
    common = make(n, rng)
    left = (1 - width) * common + width * make(n, rng)
    right = (1 - width) * common + width * make(n, rng)
    return np.stack([left, right], axis=1)


def seamless(x, loop_n, fade_n):
    """Überblendet Ende und Anfang, damit der Loop ohne Klick wiederholt werden kann."""
    y = x[:loop_n].copy()
    ramp = np.linspace(0, 1, fade_n)[:, None]
    y[:fade_n] = x[:fade_n] * np.sqrt(ramp) + x[loop_n : loop_n + fade_n] * np.sqrt(1 - ramp)
    return y


# ----------------------------------------------------------------- Sounds
def snd_rain(n, rng):
    def ch(n, rng):
        base = filt(filt(colored_noise(n, rng, 1.0), "high", 400), "low", 9000) * 0.6
        base *= lfo(n, rng, 0.08, 0.25)
        kernels = [decay_kernel(rng, rng.uniform(6, 20), 1500, 7000) for _ in range(8)]
        pos = events(n, rng, rng.uniform(60, 140))
        drops = place(n, pos, rng.pareto(3, len(pos)) * 0.4 + 0.1, kernels, rng)
        return base + drops
    return stereo(ch, n, rng, 0.7)


def snd_roof(n, rng):
    def ch(n, rng):
        kernels = [decay_kernel(rng, rng.uniform(15, 40), 700, 2600, tonal=0.5) for _ in range(6)]
        dens = lfo(n, rng, 0.05, 0.4)
        pos = events(n, rng, rng.uniform(15, 35), dens)
        return place(n, pos, rng.uniform(0.2, 1.0, len(pos)), kernels, rng)
    return stereo(ch, n, rng, 0.8)


def snd_thunder(n, rng):
    out = np.zeros(n)
    rumble = filt(colored_noise(n, rng, 2.0), "low", 180)
    env = np.zeros(n)
    t = int(rng.uniform(5, 25) * SR)
    while t < n:
        att, dec = rng.uniform(0.3, 1.2), rng.uniform(5, 11)
        seg = np.arange(int((att + dec) * SR))
        e = np.where(seg < att * SR, seg / (att * SR), np.exp(-(seg - att * SR) / (dec * SR / 4)))
        e *= rng.uniform(0.4, 1.0)
        end = min(n, t + len(seg))
        env[t:end] += e[: end - t]
        crack = filt(rng.standard_normal(int(0.6 * SR)), "band", [300, 2000], 2)
        crack *= np.exp(-np.arange(len(crack)) / (0.12 * SR)) * rng.uniform(0.1, 0.4)
        cend = min(n, t + len(crack))
        out[t:cend] += crack[: cend - t]
        t += int(rng.uniform(20, 55) * SR)
    out += rumble * env * lfo(n, rng, 2.0, 0.4)
    return np.stack([out, np.roll(out, int(0.012 * SR))], axis=1)


def snd_wind(n, rng):
    def ch(n, rng):
        a = filt(colored_noise(n, rng, 1.0), "band", [150, 900], 2) * lfo(n, rng, 0.12, 0.7)
        b = filt(colored_noise(n, rng, 1.0), "band", [600, 2200], 2) * lfo(n, rng, 0.2, 0.8) * 0.4
        return np.clip(a, -10, 10) + b
    return stereo(ch, n, rng, 0.5)


def snd_fire(n, rng):
    def ch(n, rng):
        rumble = filt(colored_noise(n, rng, 2.0), "low", 280) * lfo(n, rng, 0.6, 0.35) * 0.9
        hiss = filt(colored_noise(n, rng, 0.5), "high", 2500) * lfo(n, rng, 0.4, 0.5) * 0.08
        click = [decay_kernel(rng, rng.uniform(1, 4), 2000, 9000) for _ in range(8)]
        pops = [decay_kernel(rng, rng.uniform(10, 30), 500, 3000) for _ in range(4)]
        dens = np.clip(lfo(n, rng, 0.3, 0.9), 0.05, None)
        p1 = events(n, rng, rng.uniform(4, 12), dens)
        p2 = events(n, rng, rng.uniform(0.2, 0.8))
        c = place(n, p1, rng.pareto(2.2, len(p1)) * 0.5 + 0.1, click, rng)
        p = place(n, p2, rng.uniform(0.6, 1.5, len(p2)), pops, rng)
        return rumble + hiss + c * 1.4 + p * 1.2
    return stereo(ch, n, rng, 0.6)


def snd_clock(n, rng):
    tick = decay_kernel(rng, 18, 1800, 2400, tonal=0.6)
    tock = decay_kernel(rng, 18, 1300, 1700, tonal=0.6)
    out = np.zeros(n + len(tick))
    for i, t in enumerate(range(0, n, SR)):
        k = tick if i % 2 == 0 else tock
        out[t : t + len(k)] += k
    out = out[:n]
    return np.stack([out * 0.9, out], axis=1)


def snd_waterfall(n, rng):
    def ch(n, rng):
        hi = filt(filt(colored_noise(n, rng, 0.3), "low", 8500), "high", 200)
        mid = filt(colored_noise(n, rng, 1.0), "band", [120, 1500], 2) * 0.9
        low = filt(colored_noise(n, rng, 2.0), "low", 150) * 0.7
        return (hi * 0.6 + mid + low) * lfo(n, rng, 0.05, 0.08)
    return stereo(ch, n, rng, 0.75)


def snd_stream(n, rng):
    def ch(n, rng):
        bed = filt(colored_noise(n, rng, 1.0), "band", [300, 3000], 2) * 0.25
        out = np.zeros(n + SR)
        pos = events(n, rng, rng.uniform(25, 60), np.clip(lfo(n, rng, 0.5, 0.6), 0.1, None))
        for p in pos:
            dur = rng.uniform(0.01, 0.04)
            t = np.arange(int(dur * SR)) / SR
            f0 = rng.uniform(400, 1400)
            phase = 2 * np.pi * np.cumsum(f0 * (1 + 2.5 * t / dur)) / SR
            out[p : p + len(t)] += np.sin(phase) * np.exp(-t / (dur / 3)) * rng.uniform(0.05, 0.3)
        return bed + out[:n]
    return stereo(ch, n, rng, 0.8)


def snd_birds(n, rng):
    out = np.zeros((n + 3 * SR, 2))
    species = [
        dict(f=rng.uniform(2500, 5500), sweep=rng.uniform(-0.5, 0.8),
             syl=(rng.integers(2, 5), rng.integers(5, 9)), dur=rng.uniform(0.04, 0.14))
        for _ in range(3)
    ]
    t = int(rng.uniform(0.5, 3) * SR)
    while t < n:
        sp = species[rng.integers(0, len(species))]
        pan = rng.uniform(0.15, 0.85)
        amp = rng.uniform(0.15, 0.5)
        cur = t
        for _ in range(rng.integers(*sp["syl"])):
            d = sp["dur"] * rng.uniform(0.8, 1.2)
            tt = np.arange(int(d * SR)) / SR
            f = sp["f"] * (1 + sp["sweep"] * tt / d) * rng.uniform(0.95, 1.05)
            ph = 2 * np.pi * np.cumsum(f) / SR
            env = np.sin(np.pi * tt / d) ** 2
            s = (np.sin(ph) + 0.2 * np.sin(2 * ph)) * env * amp
            end = min(cur + len(s), len(out))
            out[cur:end, 0] += s[: end - cur] * (1 - pan)
            out[cur:end, 1] += s[: end - cur] * pan
            cur += int((d + rng.uniform(0.03, 0.12)) * SR)
        t += int(rng.uniform(1.5, 9) * SR)
    out = out[:n]
    ir = rng.standard_normal(int(0.35 * SR)) * np.exp(-np.arange(int(0.35 * SR)) / (0.08 * SR)) * 0.05
    for c in range(2):
        out[:, c] += signal.fftconvolve(out[:, c], ir)[:n]
    return out


SOUNDS = {
    "rain": snd_rain, "roof": snd_roof, "thunder": snd_thunder, "wind": snd_wind,
    "fire": snd_fire, "clock": snd_clock, "waterfall": snd_waterfall,
    "stream": snd_stream, "birds": snd_birds,
}

# Welche Sounds landen in welchem Kanal-Ordner
PLAN = {
    "regen": ["rain", "roof", "thunder", "wind"],
    "kamin": ["fire", "wind", "rain", "clock"],
    "wasserfall": ["waterfall", "stream", "birds", "wind"],
}


def write_flac(path, data):
    data = data / (np.max(np.abs(data)) + 1e-12) * 0.89  # Spitze ca. -1 dBFS
    pcm = (data * 32767).astype(np.int16)
    with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
        wavfile.write(tmp.name, SR, pcm)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp.name,
                        "-c:a", "flac", "-f", "flac", str(path) + ".part"], check=True)
    Path(str(path) + ".part").replace(path)  # erst fertige Dateien landen im Cache


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variants", type=int, default=3, help="Varianten pro Sound")
    ap.add_argument("--seconds", type=int, default=180, help="Loop-Länge in Sekunden")
    ap.add_argument("--channels", nargs="*", default=list(PLAN), help="nur diese Kanäle")
    ap.add_argument("--force", action="store_true", help="vorhandene Dateien überschreiben")
    args = ap.parse_args()

    loop_n, fade_n = args.seconds * SR, 4 * SR
    for chan in args.channels:
        out_dir = ASSETS / chan / "audio"
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in PLAN[chan]:
            for v in range(1, args.variants + 1):
                path = out_dir / f"{name}_{v:02d}.flac"
                if path.exists() and not args.force:
                    continue
                # fester Seed je Kanal/Sound/Variante -> reproduzierbar, aber überall verschieden
                seed = sum(map(ord, chan + name)) * 1000 + v
                rng = np.random.default_rng(seed)
                raw = SOUNDS[name](loop_n + fade_n, rng)
                write_flac(path, seamless(raw, loop_n, fade_n))
                print(f"  ✓ {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
