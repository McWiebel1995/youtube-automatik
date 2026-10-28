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
           "walking backwards, gore, dismemberment, 3d render, cgi, nsfw, cleavage, fanservice")


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


@app.cls(gpu="L4", image=voice_image, volumes={"/models": models}, timeout=1800, scaledown_window=120)
class VoiceDE:
    """Chatterbox Multilingual (MIT) – deutsche Sprachausgabe mit Ausdruck (für die Kinderkanäle)."""
    @modal.enter()
    def load(self):
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        self.model = ChatterboxMultilingualTTS.from_pretrained(device="cuda")
        models.commit()

    @modal.method()
    def speak(self, text: str, ref_wav: bytes = b"", exaggeration: float = 0.5, cfg_weight: float = 0.5,
              language: str = "de", seed: int = 0) -> bytes:
        import soundfile as sf
        import torch
        torch.manual_seed(seed)
        kw = {}
        if ref_wav:
            with open("/tmp/ref_de.wav", "wb") as f:
                f.write(ref_wav)
            kw["audio_prompt_path"] = "/tmp/ref_de.wav"
        wav = self.model.generate(text, language_id=language, exaggeration=exaggeration, cfg_weight=cfg_weight, **kw)
        buf = io.BytesIO()
        sf.write(buf, wav.squeeze(0).cpu().numpy(), self.model.sr, format="WAV")
        return buf.getvalue()


# ================================================================ V2: konsistente Figuren + flüssige Animation
# Qwen-Image-Edit (Apache 2.0): Figur aus Referenzbild(ern) in neue Szene setzen  (≈ "Nano Banana", offen)
# Wan 2.2 I2V A14B (Apache 2.0): großes Bild-zu-Video-Modell                     (≈ "Seedance", offen)
image_v2 = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "git")
    .pip_install(
        "torch==2.6.0", "torchvision==0.21.0",
        "git+https://github.com/huggingface/diffusers", "transformers>=4.51", "accelerate>=1.6",
        "safetensors", "sentencepiece", "ftfy", "imageio", "imageio-ffmpeg", "pillow", "numpy<2.3", "huggingface_hub", "peft>=0.15",
    )
    .env({"HF_HOME": "/models/hf", "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"})
)
EDIT_MODELS = ["Qwen/Qwen-Image-Edit-2509", "Qwen/Qwen-Image-Edit"]
I2V14 = "Wan-AI/Wan2.2-I2V-A14B-Diffusers"


@app.function(image=image_v2, volumes={"/models": models}, timeout=7200, cpu=4, memory=8192)
def download_v2():
    """Lädt die großen Modelle einmal ins Volume – auf CPU (kostet kaum Guthaben)."""
    from huggingface_hub import snapshot_download
    for repo in [EDIT_MODELS[0], I2V14]:
        snapshot_download(repo, cache_dir="/models/hf/hub")
        models.commit()
    return "ok"


@app.cls(gpu="A100-80GB", image=image_v2, volumes={"/models": models}, timeout=3600, scaledown_window=120,
         memory=98304)
class KeyframeV2:
    @modal.enter()
    def load(self):
        import torch
        self.torch = torch
        self.mode, self.err = None, None
        try:
            from diffusers import QwenImageEditPlusPipeline
            self.pipe = QwenImageEditPlusPipeline.from_pretrained(EDIT_MODELS[0], torch_dtype=torch.bfloat16)
            self.mode = "plus"
        except Exception as e:  # noqa: BLE001
            self.err = repr(e)[:200]
            from diffusers import QwenImageEditPipeline
            self.pipe = QwenImageEditPipeline.from_pretrained(EDIT_MODELS[1], torch_dtype=torch.bfloat16)
            self.mode = "edit"
        self.pipe.enable_model_cpu_offload()
        print("Qwen-Edit:", self.mode, self.err or "")

    @modal.method()
    def edit(self, ref_pngs: list, prompt: str, seed: int = 0, steps: int = 30) -> dict:
        from PIL import Image
        refs = [Image.open(io.BytesIO(b)).convert("RGB") for b in ref_pngs][:3]
        gen = self.torch.Generator("cuda").manual_seed(seed)
        neg = "lowres, blurry, text, watermark, logo, bad anatomy, extra fingers, 3d, photo, nsfw, gore"
        kw = dict(prompt=prompt, negative_prompt=neg, num_inference_steps=steps, true_cfg_scale=4.0, generator=gen)
        if self.mode == "plus":
            out = self.pipe(image=refs if len(refs) > 1 else refs[0], **kw).images[0]
        else:
            out = self.pipe(image=refs[0], **kw).images[0]
        out = out.convert("RGB")
        w, h = out.size                                          # auf 16:9 zuschneiden
        tw, th = (w, int(w * 9 / 16)) if h > w * 9 / 16 else (int(h * 16 / 9), h)
        out = out.crop(((w - tw) // 2, (h - th) // 2, (w + tw) // 2, (h + th) // 2)).resize((1344, 756))
        buf = io.BytesIO()
        out.save(buf, format="PNG")
        return {"png": buf.getvalue(), "mode": self.mode}


@app.cls(gpu="A100-80GB", image=image_v2, volumes={"/models": models}, timeout=3600, scaledown_window=120,
         memory=98304)
class AnimateV2:
    @modal.enter()
    def load(self):
        import torch
        from diffusers import WanImageToVideoPipeline
        self.torch = torch
        self.pipe = WanImageToVideoPipeline.from_pretrained(I2V14, torch_dtype=torch.bfloat16)
        # Lightning-LoRA (lightx2v, Apache 2.0): 4–8 statt 30 Schritte -> vielfach schneller
        self.fast, self.fast_err = False, None
        try:
            from huggingface_hub import list_repo_files
            files = [f for f in list_repo_files("lightx2v/Wan2.2-Lightning") if f.endswith(".safetensors")
                     and "I2V" in f and "A14B" in f]
            hi = sorted(f for f in files if "high_noise" in f)[-1]
            lo = sorted(f for f in files if "low_noise" in f)[-1]
            self.pipe.load_lora_weights("lightx2v/Wan2.2-Lightning", weight_name=hi, adapter_name="l_hi")
            self.pipe.load_lora_weights("lightx2v/Wan2.2-Lightning", weight_name=lo, adapter_name="l_lo",
                                        load_into_transformer_2=True)
            self.pipe.set_adapters(["l_hi", "l_lo"], adapter_weights=[1.0, 1.0])
            self.fast = True
        except Exception as e:  # noqa: BLE001
            self.fast_err = repr(e)[:300]
        print("Lightning:", self.fast, self.fast_err or "")
        self.pipe.enable_model_cpu_offload()
        try:
            self.pipe.vae.enable_tiling()
        except Exception:  # noqa: BLE001
            pass

    @modal.method()
    def animate(self, image_png: bytes, prompt: str, num_frames: int = 49, seed: int = 0, steps: int = 30,
                width: int = 832, height: int = 480) -> dict:
        import numpy as np
        from diffusers.utils import export_to_video
        from PIL import Image
        img = Image.open(io.BytesIO(image_png)).convert("RGB").resize((width, height))
        gen = self.torch.Generator("cuda").manual_seed(seed)
        num_frames = max(17, min(81, (num_frames - 1) // 4 * 4 + 1))
        frames = self.pipe(image=img, prompt="1990s retro cel anime, hand-drawn animation, fluid motion. " + prompt,
                           negative_prompt=WAN_NEG, height=height, width=width, num_frames=num_frames,
                           guidance_scale=1.0 if self.fast else 3.5,
                           num_inference_steps=6 if self.fast else steps, generator=gen).frames[0]
        export_to_video(frames, "/tmp/v2.mp4", fps=16)
        last = frames[-1]
        if not isinstance(last, Image.Image):
            last = Image.fromarray((np.asarray(last) * 255).clip(0, 255).astype("uint8"))
        buf = io.BytesIO()
        last.save(buf, format="PNG")
        with open("/tmp/v2.mp4", "rb") as f:
            return {"mp4": f.read(), "last_png": buf.getvalue(), "frames": num_frames,
                    "note": None if self.fast else f"ohne Lightning: {self.fast_err}"}


# ================================================================ What-if: realistische KI-Bilder
@app.function(image=image_v2, volumes={"/models": models}, timeout=7200, cpu=4, memory=8192)
def download_flux():
    """Bildmodell für What-if vorab laden (Qwen-Image, Apache 2.0, frei zugänglich)."""
    from huggingface_hub import snapshot_download
    snapshot_download("Qwen/Qwen-Image", cache_dir="/models/hf/hub")
    models.commit()
    return "ok"


@app.cls(gpu="A100-80GB", image=image_v2, volumes={"/models": models}, timeout=3600, scaledown_window=120,
         memory=98304)
class ImageFlux:
    """Fotorealistische/cineastische Bilder mit Qwen-Image (Apache 2.0)."""
    @modal.enter()
    def load(self):
        import torch
        from diffusers import DiffusionPipeline
        self.torch = torch
        self.pipe = DiffusionPipeline.from_pretrained("Qwen/Qwen-Image", torch_dtype=torch.bfloat16)
        self.pipe.enable_model_cpu_offload()

    @modal.method()
    def generate(self, prompt: str, seed: int = 0, width: int = 1664, height: int = 928, negative: str = "") -> bytes:
        gen = self.torch.Generator("cuda").manual_seed(seed)
        img = self.pipe(prompt=prompt, negative_prompt="text, watermark, logo, blurry, lowres, deformed, cartoon" + (", " + negative if negative else ""),
                        width=width, height=height, num_inference_steps=22, true_cfg_scale=4.0,
                        generator=gen).images[0]
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
