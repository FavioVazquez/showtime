"""Editing real footage by transcript, fully local.

Modules (import lazily; heavy dependencies load on first use):

    transcribe   word-level ASR (faster-whisper or Parakeet via sherpa-onnx),
                 guards against hallucinated text, cached per source hash
    refine       snap word edges to the audio energy envelope
    diarize      speaker labels (sherpa-onnx, no account or token)
    events       audio events such as (laughter) or (applause) (CED tagger)
    pack         phrase-level takes_packed.md for reading a whole shoot at once
    cuts         transcript cut algebra: remove fillers / silences / word ranges
    edl          the edit decision list: schema, validation, frame-exact plan
    render_edl   EDL -> finished video (segments, concat, overlays, audio, captions)
    captions     ASS captions in several styles + SRT / VTT export
    grade, luts  colour correction, original .cube looks
    reframe      face-tracked crop for 9:16 / 1:1
    denoise      speech denoise (DeepFilterNet / RNNoise / FFT fallback)
    stabilize    two-pass stabilisation (vid.stab, deshake fallback)
    scenes       shot detection + contact sheets
    timeline_view  filmstrip + waveform + words PNG for self-review

Transcript format (every tool reads and writes it):

    {"source": "/abs/clip.mp4", "duration": 42.1, "language": "en", "model": "...",
     "words": [{"id": "w0", "text": "Hello", "start": 0.52, "end": 0.81, "type": "word",
                "speaker": "S0", "conf": 0.93},
               {"text": " ", "start": 0.81, "end": 1.2, "type": "spacing"},
               {"text": "(laughter)", "start": 5.1, "end": 6.0, "type": "audio_event"}]}
"""

TRANSCRIPT_VERSION = 1
