"""Local narration: text-to-speech with exact word timings, alignment, mastering.

Public entry points (import lazily; numpy/onnxruntime load on first use):

    from st.voice import tts, align, master, script
    speech = tts.synthesize("Hello there.", voice="af_heart")   # -> tts.Speech
    speech.save("vo.wav")                                       # also writes vo.words.json
    words, method, dur = align.align("vo.wav", "Hello there.", lang="en")
    master.master("vo.wav", "vo.master.wav", lufs=-16)
    script.build("script.md", "voice/")                      # per-line clips + timeline.json

Engines live in st.voice.engines (kokoro: default, exact timings;
supertonic: optional multilingual; piper: fast fallback via sherpa-onnx).
"""

SAMPLE_RATE_OUT = 48000      # rate of mastered / combined outputs
TIMELINE_VERSION = 1
