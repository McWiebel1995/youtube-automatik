"""
KI 3 – GPU-Teil auf Modal (modal.com, 30 $ Gratis-Guthaben pro Monat).

  keyframe(): Anime-Standbild pro Shot  – Animagine XL 4.0 (SDXL, Lizenz: CreativeML Open RAIL++-M)
  animate():  Standbild -> 5-s-Clip     – Wan 2.2 TI2V-5B (Lizenz: Apache 2.0)

Modelle werden beim ersten Lauf einmal in ein Modal-Volume geladen und danach wiederverwendet.
Der Container schaltet sich nach 2 Minuten ohne Arbeit ab (nur echte Rechenzeit kostet Guthaben).
"""
import io

import modal

app = modal.App("anime-studio")
models = modal.Volume.from_name("anime-models", create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "git")
    .pip_install(
        "torch==2.6.0", "torchvision==0.21.0",
        "diffusers>=0.35.0", "transformers>=4.51", "accelerate>=1.6", "safetensors",
        "sentencepiece", "ftfy", "imageio", "imageio-ffmpeg", "pillow", "numpy<2.3",
    )
    .env({"HF_HOME": "/models/hf", "HF_HUB_ENABLE_HF_TRANSFER": "0",
          "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"})
)

IMAGE_MODEL = "cagliostrolab/animagine-xl-4.0"
VIDEO_MODEL = "Wan-AI/Wan2.2-TI2V-5B-Diffusers"
WAN_NEG = ("static, blurry details, subtitles, text, watermark, logo, worst quality, low quality, jpeg artifacts, "
           "ugly, deformed, extra fingers, bad hands, bad face, fused fingers, messy background, three legs, "
           "walking backwards, gore, dismemberment, 3d render, cgi")


@app.cls(gpu="L40S", image=image, volumes={"/models": models}, timeout=3600, scaledown_window=120)
class Studio:
    @modal.enter()
    def load(self):
        import torch
        from diffusers import AutoencoderKLWan, StableDiffusionXLPipeline, WanImageToVideoPipeline, WanPipeline

        self.torch = torch
        # Alle Modelle bleiben im Arbeitsspeicher; auf die GPU kommt immer nur das gerade gebrauchte
        # (sonst reicht der Grafikspeicher nicht für Bild- UND Videomodell).
        # Bildmodell + IP-Adapter (hält Figuren über alle Shots gleich: Referenzbild -> neue Szene)
        self.ip_ok, self.ip_err = False, None
        try:
            from transformers import CLIPVisionModelWithProjection
            enc = CLIPVisionModelWithProjection.from_pretrained(
                "h94/IP-Adapter", subfolder="models/image_encoder", torch_dtype=torch.float16)
            self.img = StableDiffusionXLPipeline.from_pretrained(
                IMAGE_MODEL, image_encoder=enc, torch_dtype=torch.float16, use_safetensors=True)
            self.img.load_ip_adapter("h94/IP-Adapter", subfolder="sdxl_models",
                                     weight_name="ip-adapter-plus_sdxl_vit-h.safetensors")
            self.ip_ok = True
        except Exception as e:  # noqa: BLE001
            self.ip_err = "IP-Adapter nicht verfügbar: " + repr(e)[:200]
            self.img = StableDiffusionXLPipeline.from_pretrained(
                IMAGE_MODEL, torch_dtype=torch.float16, use_safetensors=True)
        print("IP-Adapter:", self.ip_ok, self.ip_err or "")
        vae = AutoencoderKLWan.from_pretrained(VIDEO_MODEL, subfolder="vae", torch_dtype=torch.float32)
        self.t2v = WanPipeline.from_pretrained(VIDEO_MODEL, vae=vae, torch_dtype=torch.bfloat16)
        try:
            self.t2v.vae.enable_tiling()
        except Exception:  # noqa: BLE001
            pass
        self.i2v, self.i2v_ok, self.i2v_err = None, False, None
        for kwargs in ({"expand_timesteps": True}, {}):   # Bild-zu-Video mit denselben Gewichten
            try:
                self.i2v = WanImageToVideoPipeline.from_pipe(self.t2v, **kwargs)
                self.i2v_ok = True
                break
            except Exception as e:  # noqa: BLE001
                self.i2v_err = repr(e)[:300]
        print("I2V verfügbar:", self.i2v_ok, self.i2v_err or "")
        self.active = None
        models.commit()

    def use(self, name):
        """Genau eine Pipeline auf die GPU (per CPU-Offload), die anderen freigeben."""
        if self.active == name:
            return getattr(self, name)
        pipe = getattr(self, name)
        pipe.enable_model_cpu_offload()
        self.active = name
        self.torch.cuda.empty_cache()
        return pipe

    @modal.method()
    def keyframe(self, prompt: str, negative: str = "", seed: int = 0,
                 width: int = 1344, height: int = 768, ref_png: bytes = b"", ref_scale: float = 0.5) -> dict:
        from PIL import Image

        gen = self.torch.Generator("cuda").manual_seed(seed)
        pos = ("1990s (style), retro artstyle, anime screencap, cel shading, film grain, masterpiece, high score, "
               "great score, absurdres, dramatic lighting, " + prompt)
        neg = ("lowres, bad anatomy, bad hands, text, error, missing finger, extra digits, cropped, worst quality, "
               "low quality, jpeg artifacts, signature, watermark, logo, blurry, gore, 3d, cgi, glossy, "
               "modern anime, " + negative)
        kw = {}
        if self.ip_ok:                    # ohne Referenz: Adapter mit Stärke 0 (Pipeline braucht trotzdem ein Bild)
            ref = Image.open(io.BytesIO(ref_png)).convert("RGB") if ref_png else Image.new("RGB", (224, 224))
            self.img.set_ip_adapter_scale(ref_scale if ref_png else 0.0)
            kw["ip_adapter_image"] = ref
        out = self.use("img")(prompt=pos, negative_prompt=neg, width=width, height=height,
                              guidance_scale=5.0, num_inference_steps=28, generator=gen, **kw).images[0]
        buf = io.BytesIO()
        out.save(buf, format="PNG")
        return {"png": buf.getvalue(), "note": self.ip_err}

    @modal.method()
    def animate(self, image_png: bytes, prompt: str, num_frames: int = 73, seed: int = 0,
                steps: int = 25, width: int = 832, height: int = 480) -> dict:
        from diffusers.utils import export_to_video
        from PIL import Image

        gen = self.torch.Generator("cuda").manual_seed(seed)
        num_frames = max(17, min(121, (num_frames - 1) // 4 * 4 + 1))
        prompt = "1990s retro cel anime, hand-drawn animation, fluid motion. " + prompt
        mode, frames, note = "i2v", None, self.i2v_err
        if self.i2v_ok and image_png:
            try:
                img = Image.open(io.BytesIO(image_png)).convert("RGB").resize((width, height))
                frames = self.use("i2v")(image=img, prompt=prompt, negative_prompt=WAN_NEG, height=height, width=width,
                                  num_frames=num_frames, guidance_scale=5.0, num_inference_steps=steps,
                                  generator=gen).frames[0]
            except Exception as e:  # noqa: BLE001
                note = "I2V fehlgeschlagen: " + repr(e)[:300]
                frames = None
        if frames is None:
            mode = "t2v"
            frames = self.use("t2v")(prompt=prompt, negative_prompt=WAN_NEG, height=height, width=width,
                              num_frames=num_frames, guidance_scale=5.0, num_inference_steps=steps,
                              generator=gen).frames[0]
        path = "/tmp/clip.mp4"
        export_to_video(frames, path, fps=24)
        with open(path, "rb") as f:
            return {"mp4": f.read(), "mode": mode, "frames": num_frames, "note": note}


# ----------------------------------------------------------------- Synchronstimmen
# Chatterbox (Resemble AI, MIT-Lizenz): ausdrucksstarke Sprachausgabe mit regelbarer Emotion.
# Jede Figur bekommt eine eigene, rein synthetische Stimme (Referenz kommt von Kokoro, nicht von echten Menschen).
voice_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg")
    .pip_install("chatterbox-tts", "soundfile")
    .env({"HF_HOME": "/models/hf"})
)


@app.cls(gpu="L4", image=voice_image, volumes={"/models": models}, timeout=1800, scaledown_window=120)
class Voice:
    @modal.enter()
    def load(self):
        from chatterbox.tts import ChatterboxTTS
        self.model = ChatterboxTTS.from_pretrained(device="cuda")
        models.commit()

    @modal.method()
    def speak(self, text: str, ref_wav: bytes, exaggeration: float = 0.6, cfg_weight: float = 0.4,
              temperature: float = 0.8, seed: int = 0) -> bytes:
        import soundfile as sf
        import torch
        torch.manual_seed(seed)
        with open("/tmp/ref.wav", "wb") as f:
            f.write(ref_wav)
        wav = self.model.generate(text, audio_prompt_path="/tmp/ref.wav", exaggeration=exaggeration,
                                  cfg_weight=cfg_weight, temperature=temperature)
        buf = io.BytesIO()
        sf.write(buf, wav.squeeze(0).cpu().numpy(), self.model.sr, format="WAV")
        return buf.getvalue()
