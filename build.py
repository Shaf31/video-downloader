"""Build a standalone Video Downloader for the OS this runs on (no Python needed on the target machine).

    pip install -r requirements.txt pyinstaller pillow   (+ pywebview on macOS/Windows)
    python build.py

Output: dist/Video Downloader.app (macOS), dist/Video Downloader.exe (Windows), dist/video-downloader (Linux).
PyInstaller can't cross-compile: build each OS on that OS (or use .github/workflows/build.yml).
"""
import os
import subprocess
import sys
from pathlib import Path

import PyInstaller.__main__

HERE = Path(__file__).resolve().parent
SEP = os.pathsep  # PyInstaller's src/dest separator


def make_icons():
    from PIL import Image, ImageDraw

    size = 1024
    img = Image.new("RGBA", (size, size))
    grad = Image.new("RGBA", (size, size))
    gd = ImageDraw.Draw(grad)
    for y in range(size):  # blue -> violet diagonal-ish gradient
        t = y / size
        gd.line([(0, y), (size, y)], fill=(int(37 + (124 - 37) * t), int(99 + (58 - 99) * t), int(235 + (237 - 235) * t), 255))
    mask = Image.new("L", (size, size))
    ImageDraw.Draw(mask).rounded_rectangle([64, 64, size - 64, size - 64], radius=200, fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    w, c = 74, size // 2
    d.line([(c, 250), (c, 640)], fill="white", width=w)
    d.line([(c - 190, 460), (c, 650), (c + 190, 460)], fill="white", width=w, joint="curve")
    d.line([(c - 250, 790), (c + 250, 790)], fill="white", width=w)
    for x, y in [(c, 250), (c, 640), (c - 190, 460), (c + 190, 460), (c - 250, 790), (c + 250, 790)]:
        d.ellipse([x - w // 2, y - w // 2, x + w // 2, y + w // 2], fill="white")

    out = HERE / "build" / "icons"
    out.mkdir(parents=True, exist_ok=True)
    png = out / "icon.png"
    img.save(png)
    img.save(out / "icon.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    if sys.platform == "darwin":
        iconset = out / "icon.iconset"
        iconset.mkdir(exist_ok=True)
        for s in (16, 32, 128, 256, 512):
            img.resize((s, s), Image.LANCZOS).save(iconset / f"icon_{s}x{s}.png")
            img.resize((s * 2, s * 2), Image.LANCZOS).save(iconset / f"icon_{s}x{s}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(out / "icon.icns")], check=True)
        return out / "icon.icns"
    return out / "icon.ico"


def main():
    from deno import find_deno_bin

    icon = make_icons()
    args = [
        str(HERE / "app.py"),
        "--name", "Video Downloader" if sys.platform != "linux" else "video-downloader",
        "--noconfirm", "--clean",
        "--distpath", str(HERE / "dist"), "--workpath", str(HERE / "build" / "pyinstaller"),
        "--specpath", str(HERE / "build"),
        "--add-data", f"{HERE / 'index.html'}{SEP}.",
        "--add-binary", f"{find_deno_bin()}{SEP}bin",
        "--collect-all", "imageio_ffmpeg",
        "--collect-data", "yt_dlp_ejs",
        "--icon", str(icon),
    ]
    if sys.platform == "darwin":
        args += ["--windowed", "--osx-bundle-identifier", "tv.madtomato.videodownloader", "--collect-all", "webview"]
    elif os.name == "nt":
        args += ["--windowed", "--onefile", "--collect-all", "webview"]
    else:
        args += ["--onefile"]  # Linux: runs in a terminal and opens your browser
    PyInstaller.__main__.run(args)


if __name__ == "__main__":
    main()
