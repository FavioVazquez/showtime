"""MusicGen generation worker. Runs inside ~/.showtime/venv-musicgen (torch +
transformers), NOT the main showtime venv, so it imports nothing from `st`.

usage: python musicgen_worker.py --prompt TEXT --seconds S --out raw.wav
       [--model DIR_OR_REPO] [--seed N] [--threads N] [--guidance 3.0]
Prints one JSON line with the result on stdout; progress goes to stderr.
"""
import argparse
import json
import os
import sys
import time


def main() -> int:
    ap = argparse.ArgumentParser(description="MusicGen worker (non-commercial weights)")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--seconds", type=float, default=15.0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="facebook/musicgen-small")
    ap.add_argument("--revision", default=None)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--guidance", type=float, default=3.0)
    a = ap.parse_args()
    import numpy as np
    import soundfile as sf
    import torch
    from transformers import AutoProcessor, MusicgenForConditionalGeneration

    threads = a.threads or max(1, min(4, (os.cpu_count() or 2) - 1))
    torch.set_num_threads(threads)
    torch.manual_seed(a.seed)
    t0 = time.time()
    kw = {"revision": a.revision} if a.revision else {}
    proc = AutoProcessor.from_pretrained(a.model, **kw)
    # safetensors only: never torch.load a pickle (the pinned repo ships model.safetensors; Intel Macs run torch 2.2.2,
    # whose torch.load has known code-execution flaws)
    model = MusicgenForConditionalGeneration.from_pretrained(a.model, use_safetensors=True, **kw)
    model.eval()
    sr = int(model.config.audio_encoder.sampling_rate)
    tokens = int(max(1.0, min(30.0, a.seconds)) * 50)
    print("loaded in %.1fs; generating %d tokens with %d threads ..." % (time.time() - t0, tokens, threads),
          file=sys.stderr, flush=True)
    inputs = proc(text=[a.prompt], padding=True, return_tensors="pt")
    t1 = time.time()
    with torch.no_grad():
        audio = model.generate(**inputs, do_sample=True, guidance_scale=a.guidance, max_new_tokens=tokens)
    x = audio[0].cpu().numpy().T.astype(np.float32)
    pk = float(np.abs(x).max()) or 1.0
    x = x / pk * 0.89
    sf.write(a.out, x, sr, subtype="FLOAT")
    print(json.dumps({"out": a.out, "sample_rate": sr, "seconds": round(len(x) / sr, 3),
                      "generate_s": round(time.time() - t1, 1), "total_s": round(time.time() - t0, 1),
                      "model": a.model}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
