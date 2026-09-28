"""Delivery helpers for finished videos.

- poster.py  : pick a poster frame, bake it into frame 0 (duration and audio
               untouched), or attach it as MP4 cover art
- exports.py : platform presets (youtube, x, linkedin, reels, tiktok, shorts,
               square) with size, bitrate, loudness and duration rules, and
               aspect conversion by blur-pad, crop or pad
- thumbs.py  : 1280x720 (or any size) thumbnails from a video frame or image

All three use st.ff for ffmpeg; frame scoring uses numpy + Pillow when
available (inside the showtime venv) and falls back to the midpoint frame.
"""
