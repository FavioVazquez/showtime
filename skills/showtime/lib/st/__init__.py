"""showtime: local video making, directed by your coding agent.

The `st` package holds the Python side of the skill. Modules that the
launcher, installer and doctor import (st.platform, st.common, st.ff,
st.doctor) are stdlib-only and Python 3.8+ compatible; everything else runs
inside the showtime virtualenv (~/.showtime/venv, Python 3.12).
"""
import os

__version__ = "0.4.0"

# onnxruntime (Kokoro, alignment, stem separation, rembg) ships Microsoft's telemetry client on Linux
# and starts it at import; this turns it off for every process that imports st, and for its children.
# The launcher sets it too (build_env), for the Node and tool processes that never import st.
os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")
