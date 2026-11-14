"""GPU-Teil für „Französisch ist einfach, oder?“ – Bilder (Qwen-Image + Qwen-Image-Edit, Apache 2.0) und Stimme
(Chatterbox Multilingual, MIT). Nutzt das vorhandene Modell-Volume, damit nichts neu geladen werden muss."""
import io

import modal

app = modal.App("sprachrap")
models = modal.Volume.from_name("anime-models", create_if_missing=True)

image_v2 = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "git")
    .pip_install(
        "torch==2.6.0", "torchvision==0.21.0",
        "git+https://github.com/huggingface/diffusers", "transformers>=4.51", "accelerate>=1.6",
        "safetensors", "sentencepiece", "ftfy", "pillow", "numpy<2.3", "huggingface_hub",
    )
    .env({"HF_HOME": "/models/hf", "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"})
)
voice_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg")
    .pip_install("chatterbox-tts", "soundfile")
    .env({"HF_HOME": "/models/hf"})
)
NEG = "text, letters, words, watermark, logo, signature, photo, 3d render, cgi, harsh shading, extra limbs, deformed, blurry"


def _png(img):
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


@app.cls(gpu=["A100-80GB", "H100"], image=image_v2, volumes={"/models": models}, timeout=3600, scaledown_window=60,
         memory=98304)
class Art:
    @modal.method()
    def make(self, base_prompt: str, scene_b_prompt: str, mouth_prompts: list, seed: int = 7) -> dict:
        import gc

        import torch
        from diffusers import DiffusionPipeline, QwenImageEditPlusPipeline
        g = lambda: torch.Generator("cuda").manual_seed(seed)  # noqa: E731
        pipe = DiffusionPipeline.from_pretrained("Qwen/Qwen-Image", torch_dtype=torch.bfloat16)
        pipe.enable_model_cpu_offload()
        a = pipe(prompt=base_prompt, negative_prompt=NEG, width=928, height=1664, num_inference_steps=26,
                 true_cfg_scale=4.0, generator=g()).images[0]
        del pipe
        gc.collect()
        torch.cuda.empty_cache()
        ed = QwenImageEditPlusPipeline.from_pretrained("Qwen/Qwen-Image-Edit-2509", torch_dtype=torch.bfloat16)
        ed.enable_model_cpu_offload()

        def edit(img, prompt):
            out = ed(image=img, prompt=prompt, negative_prompt=NEG, num_inference_steps=26, true_cfg_scale=4.0,
                     generator=g()).images[0]
            return out.convert("RGB").resize(img.size)
        b = edit(a, scene_b_prompt)
        res = {"A": _png(a), "B": _png(b), "A_m": [], "B_m": []}
        for key, img in (("A", a), ("B", b)):
            for p in mouth_prompts:
                res[f"{key}_m"].append(_png(edit(img, p)))
        return res


@app.cls(gpu="L4", image=voice_image, volumes={"/models": models}, timeout=1800, scaledown_window=60)
class Voice:
    @modal.enter()
    def load(self):
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        self.model = ChatterboxMultilingualTTS.from_pretrained(device="cuda")

    @modal.method()
    def speak_many(self, lines: list, ref_wav: bytes, exaggeration: float = 0.65, cfg_weight: float = 0.4) -> list:
        import soundfile as sf
        import torch
        with open("/tmp/ref.wav", "wb") as f:
            f.write(ref_wav)
        out = []
        for i, (text, lang) in enumerate(lines):
            torch.manual_seed(11 + i)
            wav = self.model.generate(text, language_id=lang, audio_prompt_path="/tmp/ref.wav",
                                      exaggeration=exaggeration, cfg_weight=cfg_weight)
            buf = io.BytesIO()
            sf.write(buf, wav.squeeze(0).cpu().numpy(), self.model.sr, format="WAV")
            out.append(buf.getvalue())
        return out
