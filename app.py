"""Local video/audio downloader: yt-dlp for extraction, ffmpeg for merging and MP3 conversion."""
import os
import shutil
import socket
import subprocess
import sys
import threading
import uuid
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
import yt_dlp

# In a packaged build (PyInstaller) bundled files live in sys._MEIPASS.
APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
DOWNLOAD_DIR = Path.home() / "Downloads" / "Video Downloader"
MP3_BITRATES = [320, 256, 192, 128]
EXE = ".exe" if os.name == "nt" else ""

app = Flask(__name__, static_folder=None)
jobs = {}
jobs_lock = threading.Lock()


def bundled(name):
    path = APP_DIR / "bin" / (name + EXE)
    return str(path) if path.exists() else None


def find_ffmpeg():
    # A system ffmpeg comes with ffprobe, so prefer it; otherwise use the portable one from imageio-ffmpeg.
    found = shutil.which("ffmpeg") or bundled("ffmpeg")
    if not found:
        try:
            import imageio_ffmpeg
            found = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:  # noqa: BLE001
            found = None
    return found


def find_js_runtimes():
    # YouTube needs a JS runtime to unlock all formats (4K, etc.).
    deno = bundled("deno") or shutil.which("deno")
    if not deno:
        try:
            from deno import find_deno_bin
            deno = find_deno_bin()
        except Exception:  # noqa: BLE001
            deno = None
    runtimes = {"deno": {"path": deno}} if deno else {}
    for name in ("node", "bun"):
        if shutil.which(name):
            runtimes[name] = {}
    return runtimes


FFMPEG = find_ffmpeg()
JS_RUNTIMES = find_js_runtimes()


def base_opts(cookies_browser=None):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "js_runtimes": JS_RUNTIMES,
    }
    if FFMPEG:
        opts["ffmpeg_location"] = FFMPEG
    if cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser,)
    return opts


def codec_name(codec):
    if not codec or codec == "none":
        return None
    c = codec.lower()
    for prefix, name in (("avc", "H.264"), ("h264", "H.264"), ("hev", "H.265"), ("hvc", "H.265"),
                         ("h265", "H.265"), ("vp09", "VP9"), ("vp9", "VP9"), ("vp8", "VP8"),
                         ("av01", "AV1"), ("mp4a", "AAC"), ("aac", "AAC"), ("opus", "Opus"),
                         ("vorbis", "Vorbis"), ("mp3", "MP3"), ("flac", "FLAC"), ("ac-3", "AC-3"),
                         ("ec-3", "E-AC-3")):
        if c.startswith(prefix):
            return name
    return codec


def size_of(f, duration):
    size = f.get("filesize") or f.get("filesize_approx")
    if not size and duration and f.get("tbr"):
        size = duration * f["tbr"] * 1000 / 8
    return int(size) if size else None


def describe(info):
    duration = info.get("duration")
    formats = [f for f in info.get("formats") or [] if f.get("ext") != "mhtml" and f.get("format_id")]
    if not formats and info.get("url"):  # single-file sources
        formats = [info]

    video, audio = [], []
    for f in formats:
        vcodec, acodec = f.get("vcodec"), f.get("acodec")
        if vcodec == "none" and acodec != "none":
            audio.append({
                "id": f["format_id"],
                "ext": f.get("ext"),
                "codec": codec_name(acodec) or "?",
                "abr": round(f.get("abr") or f.get("tbr") or 0) or None,
                "asr": f.get("asr"),
                "size": size_of(f, duration),
                "lang": f.get("language"),
            })
        elif vcodec != "none":
            height = f.get("height")
            res = f.get("resolution") or ""
            if not height and res.endswith("p") and res[:-1].isdigit():
                height = int(res[:-1])
            video.append({
                "id": f["format_id"],
                "ext": f.get("ext"),
                "height": height,
                "width": f.get("width"),
                "fps": round(f["fps"]) if f.get("fps") else None,
                "codec": codec_name(vcodec) or "?",
                "tbr": round(f.get("vbr") or f.get("tbr") or 0) or None,
                "size": size_of(f, duration),
                "has_audio": acodec != "none",
                "hdr": (f.get("dynamic_range") or "SDR") != "SDR",
            })

    video.sort(key=lambda v: (v["height"] or 0, v["fps"] or 0, v["hdr"], v["tbr"] or 0), reverse=True)
    audio.sort(key=lambda a: (a["abr"] or 0, a["size"] or 0), reverse=True)

    return {
        "title": info.get("title") or "Untitled",
        "uploader": info.get("uploader") or info.get("channel"),
        "duration": duration,
        "thumbnail": info.get("thumbnail"),
        "site": info.get("extractor_key"),
        "webpage_url": info.get("webpage_url"),
        "video": video,
        "audio": audio,
        "mp3": MP3_BITRATES,
    }


@app.get("/")
def index():
    return send_from_directory(APP_DIR, "index.html")


@app.post("/api/info")
def api_info():
    body = request.get_json(force=True)
    url = (body.get("url") or "").strip()
    if not url:
        return jsonify(error="Paste a link first."), 400
    try:
        with yt_dlp.YoutubeDL(base_opts(body.get("cookies"))) as ydl:
            info = ydl.extract_info(url, download=False)
        if info.get("_type") == "playlist":
            entries = [e for e in info.get("entries") or [] if e]
            if not entries:
                return jsonify(error="No videos found at this link."), 400
            info = entries[0]
        return jsonify(describe(info))
    except yt_dlp.utils.DownloadError as e:
        return jsonify(error=clean_error(e)), 400
    except Exception as e:  # noqa: BLE001
        return jsonify(error=str(e)), 500


def clean_error(e):
    msg = str(e).replace("ERROR: ", "")
    return msg.split("; please report")[0]


def build_job_opts(kind, choice, video_meta, job):
    out = str(DOWNLOAD_DIR / "%(title).120B [%(id)s].%(ext)s")
    opts = {"outtmpl": out, "windowsfilenames": True, "overwrites": True}

    if kind == "video":
        if choice == "best":
            opts["format"] = "bv*+ba/b"
        elif video_meta and not video_meta.get("has_audio"):
            # Video-only stream: pair it with the best audio (AAC first so MP4 plays everywhere).
            pref = "ba[ext=m4a]/ba" if video_meta.get("ext") == "mp4" else "ba"
            opts["format"] = f"{choice}+{pref}/{choice}"
        else:
            opts["format"] = choice
        opts["merge_output_format"] = "mp4"
        opts["postprocessors"] = [{"key": "FFmpegMetadata", "add_metadata": True}]
    else:
        if choice.startswith("mp3-"):
            opts["format"] = "ba/b"
            opts["postprocessors"] = [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": choice[4:]},
                {"key": "FFmpegMetadata", "add_metadata": True},
            ]
        else:
            # Original stream, no re-encode: just put it in its natural container (.m4a / .opus).
            opts["format"] = choice
            opts["postprocessors"] = [
                {"key": "FFmpegExtractAudio", "preferredcodec": "best"},
                {"key": "FFmpegMetadata", "add_metadata": True},
            ]

    def on_progress(d):
        if d["status"] == "downloading":
            fid = d.get("info_dict", {}).get("format_id")
            if fid and fid not in job["_seen"]:
                job["_seen"].append(fid)
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            job.update(
                stage="Downloading" + (f" part {len(job['_seen'])}" if job["_parts"] > 1 else ""),
                percent=round(d.get("downloaded_bytes", 0) * 100 / total, 1) if total else None,
                speed=d.get("speed"),
                eta=d.get("eta"),
            )

    def on_postprocess(d):
        if d["status"] == "started":
            label = {"Merger": "Merging video + audio", "ExtractAudio": "Converting audio",
                     "FFmpegMetadata": "Writing metadata"}.get(d.get("postprocessor"), "Processing")
            if d.get("postprocessor") == "ExtractAudio" and choice.startswith("mp3-"):
                label = f"Converting to MP3 {choice[4:]} kbps"
            job.update(stage=label, percent=None, speed=None, eta=None)

    opts["progress_hooks"] = [on_progress]
    opts["postprocessor_hooks"] = [on_postprocess]
    return opts


def run_job(job_id, url, kind, choice, video_meta, cookies):
    job = jobs[job_id]
    try:
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        opts = {**base_opts(cookies), **build_job_opts(kind, choice, video_meta, job)}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        if info.get("_type") == "playlist":
            info = next(e for e in info["entries"] if e)
        path = (info.get("requested_downloads") or [{}])[0].get("filepath") or info.get("filepath")
        job.update(status="done", stage="Done", percent=100, path=path,
                   filename=os.path.basename(path) if path else None)
    except Exception as e:  # noqa: BLE001
        job.update(status="error", error=clean_error(e))


@app.post("/api/download")
def api_download():
    body = request.get_json(force=True)
    url, kind, choice = body.get("url"), body.get("kind"), body.get("choice")
    if not url or kind not in ("video", "audio") or not choice:
        return jsonify(error="Missing link or selection."), 400
    video_meta = body.get("meta") or {}
    parts = 2 if kind == "video" and (choice == "best" or not video_meta.get("has_audio", True)) else 1
    job_id = uuid.uuid4().hex
    with jobs_lock:
        jobs[job_id] = {"status": "running", "stage": "Starting", "percent": None,
                        "_seen": [], "_parts": parts}
    threading.Thread(target=run_job, daemon=True,
                     args=(job_id, url, kind, choice, video_meta, body.get("cookies"))).start()
    return jsonify(job=job_id)


@app.get("/api/progress/<job_id>")
def api_progress(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify(error="Unknown job"), 404
    return jsonify({k: v for k, v in job.items() if not k.startswith("_")})


@app.post("/api/reveal/<job_id>")
def api_reveal(job_id):
    path = (jobs.get(job_id) or {}).get("path")
    exists = bool(path) and os.path.exists(path)
    target = path if exists else str(DOWNLOAD_DIR)
    if sys.platform == "darwin":
        subprocess.run(["open", "-R", target] if exists else ["open", target], check=False)
    elif os.name == "nt":
        subprocess.run(["explorer", "/select,", target] if exists else ["explorer", target], check=False)
    else:
        subprocess.run(["xdg-open", os.path.dirname(target) if exists else target], check=False)
    return jsonify(ok=True)


@app.get("/api/status")
def api_status():
    return jsonify(ffmpeg=bool(FFMPEG), folder=str(DOWNLOAD_DIR), ytdlp=yt_dlp.version.__version__,
                   platform=sys.platform, window=WINDOW_MODE)


@app.post("/api/quit")
def api_quit():
    threading.Timer(0.3, lambda: os._exit(0)).start()
    return jsonify(ok=True)


WINDOW_MODE = False


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    global WINDOW_MODE
    port = int(os.environ.get("PORT") or free_port())
    url = f"http://127.0.0.1:{port}"
    threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port, threaded=True), daemon=True).start()
    print(f"Video Downloader running at {url}")

    # Open in a native app window when possible; closing the window quits the app.
    if os.environ.get("VD_BROWSER") != "1":
        try:
            import webview
            WINDOW_MODE = True
            webview.create_window("Video Downloader", url, width=1240, height=860, min_size=(820, 600))
            webview.start()
            return
        except Exception as e:  # noqa: BLE001
            WINDOW_MODE = False
            print(f"No native window available ({e}); opening your browser instead.")

    if os.environ.get("VD_NO_OPEN") != "1":
        webbrowser.open(url)
    print("Close this window (or click Quit in the app) to stop.")
    threading.Event().wait()


if __name__ == "__main__":
    main()
