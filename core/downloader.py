from __future__ import annotations
import yt_dlp
from PySide6.QtCore import QThread, Signal

# ---------------------------------------------------------------------------
# Format string builder
# ---------------------------------------------------------------------------

QUALITY_HEIGHT: dict[str, int | None] = {
    "144p": 144,
    "240p": 240,
    "360p": 360,
    "480p": 480,
    "720p": 720,
    "1080p": 1080,
    "best": None,
}

CODEC_PREFIX: dict[str, str] = {
    "H.264": "avc1",
    "VP9": "vp09",
    "AV1": "av01",
}

# Save format → output spec.
#   video: merged into the given container (merge_output_format).
#   audio: video is discarded and audio is extracted to the given codec
#          (FFmpegExtractAudio); quality/codec selections do not apply.
SAVE_FORMATS: dict[str, dict] = {
    "MP4":  {"kind": "video", "container": "mp4"},
    "MKV":  {"kind": "video", "container": "mkv"},
    "WebM": {"kind": "video", "container": "webm"},
    "MP3":  {"kind": "audio", "audiocodec": "mp3"},
    "M4A":  {"kind": "audio", "audiocodec": "m4a"},
}


def is_audio_format(save_format: str) -> bool:
    return SAVE_FORMATS.get(save_format, {}).get("kind") == "audio"


def build_format_string(quality: str) -> str:
    height = QUALITY_HEIGHT.get(quality)
    hf = f"[height<={height}]" if height else ""
    # Pick the highest-resolution video within the height cap, then fall back to
    # a single combined stream. Codec is NOT filtered here — it is expressed as a
    # preference via format_sort (see build_format_sort), so choosing H.264 never
    # caps the resolution below an available higher-res VP9/AV1 stream.
    return f"bv*{hf}+ba/b{hf}/b"


def build_format_sort(codec: str) -> list[str]:
    vcodec = CODEC_PREFIX.get(codec, "avc1")
    # Resolution dominates; the chosen codec only breaks ties between formats of
    # equal resolution. This keeps "best" truly best (e.g. 2160p VP9/AV1) while
    # still preferring the requested codec when there is a real choice.
    return ["res", f"vcodec:{vcodec}"]


# ---------------------------------------------------------------------------
# yt-dlp logger that routes messages to the worker's signals
# ---------------------------------------------------------------------------

class _YtdlpLogger:
    def __init__(self, worker: DownloadWorker):
        self._worker = worker

    def debug(self, msg: str) -> None:
        # yt-dlp uses debug() for many informational messages; suppress [debug] lines
        if msg.startswith("[debug]"):
            return
        self._worker.log_message.emit(msg)

    def info(self, msg: str) -> None:
        self._worker.log_message.emit(msg)

    def warning(self, msg: str) -> None:
        self._worker.log_message.emit(f"[WARNING] {msg}")

    def error(self, msg: str) -> None:
        self._worker.log_message.emit(f"[ERROR] {msg}")


# ---------------------------------------------------------------------------
# Download worker (runs in a separate thread)
# ---------------------------------------------------------------------------

class DownloadWorker(QThread):
    # Emitted from the worker thread — connected to UI slots in the main thread
    progress_updated = Signal(float, str)   # (percent 0-100, status line)
    log_message = Signal(str)               # informational log line
    download_finished = Signal(bool, str)   # (success, message)
    # Emitted on success with the final file path + metadata, so the main thread
    # can register the clip into the active library DB. Payload keys:
    #   file_path, source_url, title, duration, width, height, vcodec,
    #   container, filesize, subtitle_path
    download_succeeded = Signal(dict)

    def __init__(
        self,
        url: str,
        output_dir: str,
        quality: str,
        codec: str,
        write_subtitles: bool,
        save_format: str = "MP4",
        parent=None,
    ):
        super().__init__(parent)
        self.url = url
        self.output_dir = output_dir
        self.quality = quality
        self.codec = codec
        self.write_subtitles = write_subtitles
        self.save_format = save_format
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    # ------------------------------------------------------------------
    # Hooks (called by yt-dlp in the worker thread)
    # ------------------------------------------------------------------

    def _progress_hook(self, d: dict) -> None:
        if self._cancelled:
            raise yt_dlp.utils.DownloadCancelled()

        status = d.get("status")

        if status == "downloading":
            downloaded = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            percent = (downloaded / total * 100.0) if total else 0.0

            speed = d.get("speed") or 0
            speed_str = f"{speed / 1024 / 1024:.1f} MB/s" if speed else "-- MB/s"
            eta = d.get("eta")
            eta_str = f"  ETA {eta}s" if eta is not None else ""
            filename = d.get("filename", "")
            import os
            short_name = os.path.basename(filename)

            status_line = f"{short_name}  {speed_str}{eta_str}"
            self.progress_updated.emit(percent, status_line)

        elif status == "finished":
            self.log_message.emit(f"Finished segment: {d.get('filename', '')}")
            self.progress_updated.emit(100.0, "Post-processing (merging)...")

        elif status == "error":
            self.log_message.emit(f"[Hook error] {d}")

    def _postprocessor_hook(self, d: dict) -> None:
        if d.get("status") == "finished":
            pp = d.get("postprocessor", "")
            self.log_message.emit(f"Post-processor done: {pp}")

    # ------------------------------------------------------------------
    # Resolution sanity check
    # ------------------------------------------------------------------

    def _warn_if_below_requested(self, info: dict) -> None:
        """Warn loudly when YouTube only offers resolutions far below the
        requested quality — usually a sign the high-res adaptive formats could
        not be deciphered (anti-bot / signature challenge) and yt-dlp is about to
        silently fall back to the 360p muxed stream."""
        formats = info.get("formats") or []
        heights = [
            f.get("height")
            for f in formats
            if f.get("vcodec") not in (None, "none") and f.get("height")
        ]
        if not heights:
            return
        max_avail = max(heights)
        self.log_message.emit(
            f"Available video resolutions: up to {max_avail}p "
            f"({', '.join(str(h) + 'p' for h in sorted(set(heights)))})"
        )

        requested = QUALITY_HEIGHT.get(self.quality)  # None == "best"
        target = requested if requested is not None else 1080
        if max_avail < target:
            self.log_message.emit(
                f"[WARNING] Requested {self.quality} but the highest available "
                f"resolution is only {max_avail}p. YouTube likely withheld the "
                f"higher-resolution formats (anti-bot / signature challenge). "
                f"Try updating yt-dlp to the latest version."
            )

    # ------------------------------------------------------------------
    # Success payload (for library auto-registration)
    # ------------------------------------------------------------------

    def _build_success_payload(self, info: dict) -> dict | None:
        """Extract the final file path + metadata from yt-dlp's info dict.

        After a successful download, yt-dlp records the final (post-merge /
        post-extract) path in ``requested_downloads[].filepath``. Returns None
        if the path could not be determined.
        """
        if not isinstance(info, dict):
            return None
        downloads = info.get("requested_downloads") or []
        entry = downloads[0] if downloads else {}
        file_path = entry.get("filepath") or info.get("filepath")
        if not file_path:
            return None

        # Subtitle sidecar: yt-dlp lists written subs in requested_subtitles.
        subtitle_path = None
        req_subs = info.get("requested_subtitles") or {}
        for sub in req_subs.values():
            if isinstance(sub, dict) and sub.get("filepath"):
                subtitle_path = sub["filepath"]
                break

        return {
            "file_path": file_path,
            "source_url": info.get("webpage_url") or self.url,
            "title": info.get("title"),
            "duration": info.get("duration"),
            "width": info.get("width"),
            "height": info.get("height"),
            "vcodec": info.get("vcodec") if info.get("vcodec") not in (None, "none") else None,
            "container": info.get("ext"),
            "filesize": info.get("filesize") or info.get("filesize_approx"),
            "subtitle_path": subtitle_path,
        }

    # ------------------------------------------------------------------
    # Thread entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        spec = SAVE_FORMATS.get(self.save_format, SAVE_FORMATS["MP4"])
        audio_only = spec["kind"] == "audio"

        ydl_opts: dict = {
            "outtmpl": f"{self.output_dir}/%(title)s.%(ext)s",
            "progress_hooks": [self._progress_hook],
            "postprocessor_hooks": [self._postprocessor_hook],
            # Subtitle options
            "writesubtitles": self.write_subtitles,
            "writeautomaticsub": self.write_subtitles,
            "subtitleslangs": ["en"],
            "subtitlesformat": "srt",
            "embedsubtitles": False,
            # Suppress internal output; we use the logger instead
            "quiet": True,
            "no_warnings": False,
            "logger": _YtdlpLogger(self),
        }

        if audio_only:
            # Grab the best audio stream and transcode it to the requested codec.
            # Quality/codec selections are about video, so they do not apply here.
            ydl_opts["format"] = "bestaudio/best"
            ydl_opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": spec["audiocodec"],
                "preferredquality": "0",  # best
            }]
            self.log_message.emit(
                f"Format: bestaudio/best | Save format: {self.save_format} "
                f"(audio-only, {spec['audiocodec']})"
            )
        else:
            fmt = build_format_string(self.quality)
            sort = build_format_sort(self.codec)
            ydl_opts["format"] = fmt
            ydl_opts["format_sort"] = sort
            ydl_opts["merge_output_format"] = spec["container"]
            self.log_message.emit(
                f"Format: {fmt} | Sort: {','.join(sort)} | "
                f"Quality: {self.quality} | Codec: {self.codec} | "
                f"Save format: {self.save_format} ({spec['container']})"
            )

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                self.log_message.emit(f"Fetching info: {self.url}")
                # Extract once, inspect available resolutions, then download from
                # the same info dict (process_ie_result re-uses it, no re-extract).
                info = ydl.extract_info(self.url, download=False)
                if not audio_only:
                    self._warn_if_below_requested(info)
                result = ydl.process_ie_result(info, download=True)
            payload = self._build_success_payload(result or info)
            if payload:
                self.download_succeeded.emit(payload)
            self.download_finished.emit(True, "Download complete.")
        except yt_dlp.utils.DownloadCancelled:
            self.download_finished.emit(False, "Download cancelled.")
        except yt_dlp.utils.DownloadError as e:
            self.download_finished.emit(False, f"Download error: {e}")
        except Exception as e:
            self.download_finished.emit(False, f"Unexpected error: {e}")
