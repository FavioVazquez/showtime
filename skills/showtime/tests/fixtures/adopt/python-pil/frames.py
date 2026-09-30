"""A frame generator the way a model writes one: render(t) -> Pillow image, piped to ffmpeg."""
import subprocess
import sys

from PIL import Image, ImageDraw

W, H = 640, 360
FPS = 24
DURATION = 2.0


def ease(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def render(t):
    im = Image.new("RGB", (W, H), (16, 20, 28))
    d = ImageDraw.Draw(im)
    k = ease(t / 1.2)
    x = 60 + k * (W - 220)
    d.rounded_rectangle((x, 130, x + 100, 230), radius=18, fill=(242, 193, 78))
    d.rectangle((60, 300, 60 + (W - 120) * t / DURATION, 312), fill=(63, 185, 80))
    return im


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "frames.mp4"
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", out],
                          stdin=subprocess.PIPE)
    for f in range(int(DURATION * FPS)):
        ff.stdin.write(render(f / FPS).tobytes())
    ff.stdin.close()
    ff.wait()
    print("wrote", out)


if __name__ == "__main__":
    main()
