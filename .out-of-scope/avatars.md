# No talking avatars or cloned faces

**Decision:** showtime does not generate synthetic presenters, lip-synced avatars, face swaps or cloned
likenesses of real people, and it does not clone voices from recordings.

**Why**
- Synthetic people and cloned likenesses are easy to misuse for impersonation, and consent is hard to
  verify from a tool.
- The local models that do this well need large GPUs and have restrictive licenses (see
  [required-gpu.md](required-gpu.md) and [non-commercial-assets.md](non-commercial-assets.md)).
- showtime's strengths are motion graphics, real footage, screen material and stock voices. A presenter
  is better filmed for real and edited with the footage tools.

**Instead:** use a stock voice for narration, the user's own recorded voice-over, or real footage of a
real presenter edited with `showtime edit`.
