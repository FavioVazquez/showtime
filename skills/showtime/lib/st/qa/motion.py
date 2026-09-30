"""Motion defects in a rendered video, read from its frame-to-frame change (st.qa.rhythm's per-frame
mean absolute luma difference at 256x144, 0-255 levels).

  dead_stop   a fast move that ends in a dead stop: at least 6 frames of real motion whose last frames
              still move at half the move's peak or more, then nothing for the next 4 frames or more. An eased
              landing (ease-out) sheds its speed over the last frames; a linear or cut-off move halts in
              one frame and reads as a glitch. Hard cuts (a one-frame spike) are not moves.

Pure numpy on the series rhythm already measured: no second decode.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence

# levels (0-255) of mean frame-to-frame change: a move worth the name, and "nothing moves"
MOVE_LEVEL = 1.2
REST_LEVEL = 0.15
MIN_MOVE_FRAMES = 6         # 0.2 s at 30 fps: a move, not a quick fade or a pop
STILL_AFTER = 4             # and it stays put: a landing, not the dark middle of a dip
KEEP_SHARE = 0.5          # the last moving frame still has >= this share of the move's peak: no settle


def dead_stops(mad: Sequence[float], fps: float, cuts: Sequence[float] = (), limit: int = 5) -> List[Dict[str, Any]]:
    """[{frame, t, last, peak, frames}] for each fast move that stops dead. `frame` is the first still frame."""
    m = [float(x) for x in mad]
    n = len(m)
    cut_frames = {int(round(c * fps)) for c in cuts} if fps else set()
    out: List[Dict[str, Any]] = []
    i = 1
    while i < n - STILL_AFTER:
        if not (m[i] >= MOVE_LEVEL * 0.5 and all(m[i + k] <= REST_LEVEL for k in range(1, STILL_AFTER + 1))):
            i += 1
            continue
        # the move that ends here: consecutive frames with at least half the move level
        j = i
        while j - 1 >= 1 and m[j - 1] >= MOVE_LEVEL * 0.5:
            j -= 1
        frames = i - j + 1
        run = m[j:i + 1]
        peak = max(run)
        near_cut = any(abs(i - c) <= 1 or abs(i + 1 - c) <= 1 for c in cut_frames)
        # a lone spike far above its neighbours is a cut or a pop, not a move
        spike = m[i] > 3.0 * (sorted(run)[len(run) // 2] if run else 0.0) and frames <= MIN_MOVE_FRAMES + 1
        # the last frame may be a partial step (the move ends between two frames): judge the last two
        last = max(m[i], m[i - 1] if frames > 1 else 0.0)
        if frames >= MIN_MOVE_FRAMES and peak >= MOVE_LEVEL and last >= KEEP_SHARE * peak and not near_cut and not spike:
            out.append({"frame": i + 1, "t": round((i + 1) / fps, 3) if fps else 0.0, "last": round(last, 2),
                        "peak": round(peak, 2), "frames": frames})
            if len(out) >= limit:
                break
        i += 2
    return out


def describe(d: Dict[str, Any], fps: float) -> Dict[str, str]:
    """The finding's message and fix, in frame numbers (the critic's vocabulary)."""
    f = int(d["frame"])
    ease_from = max(0, f - 8)
    msg = ("a fast move stops dead at frame %d (%.2fs): its last moving frame still changes %.1f levels (%d%% of "
           "its peak), the next frame nothing, with no settle" % (f, d["t"], d["last"], round(100 * d["last"] / max(1e-9, d["peak"]))))
    fix = ("ease it out: let the move shed its speed over its last 6-10 frames (from about frame %d, `power3.out` or "
           "`premium`), or land it earlier and hold; never end a move on a linear or cut-off curve" % ease_from)
    return {"message": msg, "fix": fix}
