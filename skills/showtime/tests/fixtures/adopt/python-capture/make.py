"""No frame function: the frame is built inline in main(), and a sine tone is muxed in (capture mode)."""
import math
import struct
import subprocess
import wave

W, H, FPS, SECONDS = 320, 180, 20, 2


def tone(path):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 48000)))
                               for i in range(48000 * SECONDS)))


def main():
    tone("tone.wav")
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", "tone.wav",
                           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", "clip.mp4"],
                          stdin=subprocess.PIPE)
    for f in range(FPS * SECONDS):
        x = int(f * (W - 40) / (FPS * SECONDS))
        row = bytearray()
        for yy in range(H):
            for xx in range(W):
                row += b"\xf2\xc1\x4e" if x <= xx < x + 40 and 70 <= yy < 110 else b"\x10\x14\x1c"
        ff.stdin.write(bytes(row))
    ff.stdin.close()
    ff.wait()
    print("wrote clip.mp4")


main()
