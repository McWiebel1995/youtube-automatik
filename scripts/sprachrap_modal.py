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
            wav = None
            # sehr kurze Texte (ein Wort) bringen Chatterbox manchmal aus dem Tritt -> mit anderem Seed/Füllung neu
            for k, t in enumerate([text, text, f"{text.rstrip('.!?')}… {text}"]):
                try:
                    torch.manual_seed(11 + i + 100 * k)
                    wav = self.model.generate(t, language_id=lang, audio_prompt_path="/tmp/ref.wav",
                                              exaggeration=exaggeration, cfg_weight=cfg_weight)
                    break
                except Exception as e:  # noqa: BLE001
                    print("Stimme, neuer Versuch:", text, repr(e)[:120])
            if wav is None:
                out.append(b"")
                continue
            buf = io.BytesIO()
            sf.write(buf, wav.squeeze(0).cpu().numpy(), self.model.sr, format="WAV")
            out.append(buf.getvalue())
        return out


# ================================================================ Rap-Song: ACE-Step 1.5 (MIT) – echter Flow im Takt
ace_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "ffmpeg", "libsndfile1", "build-essential", "curl")
    .pip_install("uv")
    .run_commands(
        "git clone --depth 1 https://github.com/ACE-Step/ACE-Step-1.5.git /app",
        "cd /app && uv sync --frozen --no-dev --python python3.11",
        "uv pip install --python /app/.venv/bin/python demucs",
    )
    .env({"ACESTEP_CHECKPOINTS_DIR": "/models/acestep", "HF_HOME": "/models/hf", "TOKENIZERS_PARALLELISM": "false"})
)

ACE_RUN = r'''
import json, sys, os, subprocess
sys.path.insert(0, "/app")
from acestep.handler import AceStepHandler
from acestep.llm_inference import LLMHandler
from acestep.inference import GenerationParams, GenerationConfig, generate_music
job = json.load(open(sys.argv[1]))
dit = AceStepHandler(); dit.initialize_service(project_root="/app", config_path="acestep-v15-turbo", device="cuda")
llm = LLMHandler(); llm.initialize(checkpoint_dir="/models/acestep", lm_model_path="acestep-5Hz-lm-1.7B", backend="pt", device="cuda")
p = GenerationParams(caption=job["caption"], lyrics=job["lyrics"], vocal_language=job["lang"], bpm=job["bpm"], duration=job["duration"])
c = GenerationConfig(batch_size=job["n"], audio_format="wav")
r = generate_music(dit, llm, p, c, save_dir="/tmp/ace_out")
if not r.success: raise SystemExit("ACE-Step: " + str(r.error))
ex = r.extra_outputs or {}
out = []
for i, a in enumerate(r.audios):
    lrc = ""
    try:
        lr = dit.get_lyric_timestamp(pred_latent=ex["pred_latents"][i:i+1], encoder_hidden_states=ex["encoder_hidden_states"][i:i+1],
            encoder_attention_mask=ex["encoder_attention_mask"][i:i+1], context_latents=ex["context_latents"][i:i+1],
            lyric_token_ids=ex["lyric_token_idss"][i:i+1], total_duration_seconds=float(job["duration"]), vocal_language=job["lang"], seed=42)
        lrc = lr.get("lrc_text", "") if lr.get("success") else ""
    except Exception as e:
        print("LRC fehlgeschlagen:", repr(e)[:200])
    subprocess.run([sys.executable, "-m", "demucs", "--two-stems=vocals", "-n", "htdemucs", "-o", "/tmp/sep", a["path"]], check=True)
    stem = os.path.splitext(os.path.basename(a["path"]))[0]
    out.append({"mix": a["path"], "vocals": f"/tmp/sep/htdemucs/{stem}/vocals.wav", "lrc": lrc})
json.dump(out, open("/tmp/ace_result.json", "w"))
'''


@app.function(gpu="L40S", image=ace_image, volumes={"/models": models}, timeout=3600, memory=32768)
def rap(caption: str, lyrics: str, lang: str = "de", bpm: int = 92, duration: float = 26.0, n: int = 2) -> list:
    import json
    import subprocess
    with open("/tmp/job.json", "w") as f:
        json.dump({"caption": caption, "lyrics": lyrics, "lang": lang, "bpm": bpm, "duration": duration, "n": n}, f)
    with open("/tmp/ace_run.py", "w") as f:
        f.write(ACE_RUN)
    subprocess.run(["/app/.venv/bin/python", "/tmp/ace_run.py", "/tmp/job.json"], check=True, cwd="/app")
    models.commit()
    res = json.load(open("/tmp/ace_result.json"))
    return [{"mix": open(r["mix"], "rb").read(), "vocals": open(r["vocals"], "rb").read(), "lrc": r["lrc"]} for r in res]
