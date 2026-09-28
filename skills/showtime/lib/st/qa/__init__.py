"""Evidence tools for finished videos.

- st.qa.video:   `showtime qa <video>` checks (probe, loudness, black/frozen/silent,
                 clipping, first frame, captions, credits, expect block) -> PASS/WARN/FAIL
- st.qa.review:  `showtime review-pack <job|video>` builds a folder a critic can judge
- st.qa.media:   ffmpeg helpers (frames, detectors, faststart, audio decode)
- st.qa.images:  contact sheets and the loudness graph (Pillow)
- st.qa.captions: SRT/VTT/ASS parsing and caption checks
"""
from __future__ import annotations

SEVERITIES = ("FAIL", "WARN", "INFO")
