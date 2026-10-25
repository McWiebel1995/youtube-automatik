"""
ClipWerk-Stimme auf Modal (eigenes Konto): spricht beliebig langen Text mit der Stimme aus einer Referenzaufnahme.
Deploy:  modal deploy desktop/modal_voice.py      (macht der Workflow .github/workflows/clipwerk.yml)
Die Referenzaufnahme wird nur für die Anfrage verwendet und nicht gespeichert.
"""
import io
import re

import modal

app = modal.App("clipwerk-voice")
image = (modal.Image.debian_slim(python_version="3.11")
         .apt_install("ffmpeg")
         .pip_install("chatterbox-tts", "soundfile", "numpy"))
models = modal.Volume.from_name("clipwerk-models", create_if_missing=True)


@app.cls(gpu="L4", image=image, volumes={"/root/.cache/huggingface": models}, timeout=1800, scaledown_window=120)
class Voice:
    @modal.enter()
    def load(self):
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        self.model = ChatterboxMultilingualTTS.from_pretrained(device="cuda")
        models.commit()

    @modal.method()
    def speak(self, text: str, ref_wav: bytes, language: str = "de", exaggeration: float = 0.5,
              cfg_weight: float = 0.5, seed: int = 7) -> bytes:
        import numpy as np
        import soundfile as sf
        import torch
        with open("/tmp/ref.wav", "wb") as f:
            f.write(ref_wav)
        # Satzweise sprechen (lange Texte bleiben stabil), kurze Pausen dazwischen
        parts = [p.strip() for p in re.split(r"(?<=[.!?…])\s+", text.strip()) if p.strip()]
        chunks, cur = [], ""
        for p in parts:                                  # sehr kurze Sätze zusammenfassen (Einzelwörter sind instabil)
            cur = f"{cur} {p}".strip()
            if len(cur) > 40:
                chunks.append(cur)
                cur = ""
        if cur:
            chunks.append(cur) if not chunks else chunks.__setitem__(-1, chunks[-1] + " " + cur)
        out = []
        for i, ch in enumerate(chunks):
            torch.manual_seed(seed + i)
            w = self.model.generate(ch, language_id=language, audio_prompt_path="/tmp/ref.wav",
                                    exaggeration=exaggeration, cfg_weight=cfg_weight).squeeze(0).cpu().numpy()
            out += [w, np.zeros(int(self.model.sr * 0.35), dtype=w.dtype)]
        buf = io.BytesIO()
        sf.write(buf, np.concatenate(out) if out else np.zeros(1000), self.model.sr, format="WAV")
        return buf.getvalue()
