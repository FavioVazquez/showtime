# No cloud APIs, API keys or accounts

**Decision:** every tool showtime runs executes on the user's machine. It does not call hosted
text-to-speech, music, image, video, transcription or avatar services, and it never asks for an API key,
token or sign-in.

**Why**
- *Privacy.* Footage, voices, screen recordings and unreleased product pages stay on the machine.
- *Cost and reliability.* A video made today can be re-rendered in a year without a subscription, a quota
  or a service that changed its API.
- *Reproducibility.* Pinned local models and binaries give the same result on every run; remote models
  change silently.
- *One install story.* `showtime setup` is the only step; there is nothing to configure per service.

**What is allowed:** downloading pinned, checksummed models and permissively licensed assets during setup
or on first use of a feature, and fetching public web pages the user points at (`showtime site capture`).

**Instead:** local engines cover each need (Kokoro/Piper/Supertonic voices, faster-whisper/Parakeet
transcription, the procedural composer and synth, the local audio library).
