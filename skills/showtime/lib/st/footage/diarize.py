"""Speaker diarization with sherpa-onnx (pyannote segmentation 3.0 + TitaNet
embeddings, ONNX, no account or token), and word -> speaker assignment.

Models (installed by `showtime setup --with diarize`):
  ~/.showtime/models/sherpa/sherpa-onnx-pyannote-segmentation-3-0/model.onnx
  ~/.showtime/models/sherpa/nemo_en_titanet_small.onnx
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..common import ShowtimeError, paths
from .. import platform as plat


def model_paths() -> Tuple[Path, Path]:
    d = paths()["sherpa"]
    seg = d / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx"
    emb = d / "nemo_en_titanet_small.onnx"
    return seg, emb


def available() -> Tuple[bool, str]:
    seg, emb = model_paths()
    missing = [p.name for p in (seg, emb) if not p.is_file()]
    if missing:
        return False, "missing models: " + ", ".join(missing)
    try:
        import sherpa_onnx  # noqa: F401
    except ImportError as e:
        return False, "sherpa-onnx not importable (%s)" % e
    return True, ""


def diarize(audio, sr: int, num_speakers: Optional[int] = None, threshold: float = 0.5,
            threads: Optional[int] = None) -> List[Tuple[float, float, int]]:
    """[(start, end, speaker_index)] sorted by start. `audio` is mono float32."""
    ok, why = available()
    if not ok:
        raise ShowtimeError("speaker diarization is not installed (%s)" % why,
                            hint="run `showtime setup --with diarize`")
    import numpy as np
    import sherpa_onnx
    seg, emb = model_paths()
    n = threads or max(1, min(4, plat.cpu_count()))
    cfg = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(seg)), num_threads=n),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(emb), num_threads=n),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=int(num_speakers) if num_speakers else -1,
                                                    threshold=float(threshold)),
        min_duration_on=0.3, min_duration_off=0.5)
    if not cfg.validate():
        raise ShowtimeError("invalid diarization configuration (models damaged?)",
                            hint="run `showtime setup --with diarize` again")
    sd = sherpa_onnx.OfflineSpeakerDiarization(cfg)
    if sr != sd.sample_rate:
        from .util import load_audio  # noqa: F401 - caller should pass 16 kHz
        raise ShowtimeError("diarization needs %d Hz audio (got %d)" % (sd.sample_rate, sr))
    res = sd.process(np.ascontiguousarray(audio, dtype=np.float32)).sort_by_start_time()
    return [(float(r.start), float(r.end), int(r.speaker)) for r in res]


def assign(words: List[Dict[str, Any]], segments: List[Tuple[float, float, int]]) -> Dict[str, Any]:
    """Label every word/event with 'S<n>' (n ordered by first appearance)."""
    order: Dict[int, int] = {}
    for s, e, spk in sorted(segments):
        order.setdefault(spk, len(order))
    last = None
    counts: Dict[str, int] = {}
    for w in words:
        if w.get("type") == "spacing":
            continue
        s, e = float(w["start"]), float(w["end"])
        best, best_ov = None, 0.0
        for a, b, spk in segments:
            ov = min(e, b) - max(s, a)
            if ov > best_ov:
                best, best_ov = spk, ov
        if best is None:
            mid = (s + e) / 2
            near = min(segments, key=lambda x: min(abs(mid - x[0]), abs(mid - x[1])), default=None)
            if near and min(abs(mid - near[0]), abs(mid - near[1])) < 0.6:
                best = near[2]
            else:
                best = last
        if best is None:
            best = 0 if not order else next(iter(order))
        last = best
        lab = "S%d" % order.get(best, best)
        w["speaker"] = lab
        counts[lab] = counts.get(lab, 0) + 1
    return {"speakers": len(counts), "words_per_speaker": counts}
