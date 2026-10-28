from __future__ import annotations

import re
import subprocess
from pathlib import Path

from app.models import Frame

_TIME_RE = re.compile(r"time=(\d+):(\d+):([\d.]+)")

AUDIO_SAMPLE_RATE = 24000


class VideoTooLong(Exception):
    pass


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([*args], check=True, capture_output=True, text=True)


def _duration_from_decode(video: Path) -> float:
    result = subprocess.run(
        ["ffmpeg", "-i", str(video), "-f", "null", "-"],
        check=False, capture_output=True, text=True,
    )
    matches = _TIME_RE.findall(result.stderr or "")
    if not matches:
        raise ValueError(f"could not determine duration of {video}")
    hours, minutes, seconds = matches[-1]
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def probe_duration_s(video: Path) -> float:
    result = _run(
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video),
    )
    text = result.stdout.strip()
    if text == "N/A":
        return _duration_from_decode(video)
    return float(text)


def check_length(video: Path, max_s: int) -> None:
    if probe_duration_s(video) > max_s:
        raise VideoTooLong(f"video is longer than {max_s}s")


def has_video_stream(path: Path) -> bool:
    """True when ffprobe finds at least one video stream in the file."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v",
         "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        check=False, capture_output=True, text=True,
    )
    return bool((result.stdout or "").strip())


def extract_audio(video: Path, out_wav: Path) -> Path:
    _run(
        "ffmpeg",
        "-y", "-i", str(video),
        "-ac", "1", "-ar", str(AUDIO_SAMPLE_RATE), "-sample_fmt", "s16",
        str(out_wav),
    )
    return out_wav


def extract_frames(video: Path, out_dir: Path, fps: float = 2.0) -> list[Frame]:
    out_dir.mkdir(parents=True, exist_ok=True)
    _run(
        "ffmpeg",
        "-y", "-i", str(video),
        "-vf", f"fps={fps}",
        "-q:v", "3",
        str(out_dir / "raw_%03d.jpg"),
    )
    frames = []
    for i, raw in enumerate(sorted(out_dir.glob("raw_*.jpg"))):
        t_ms = round(i * 1000 / fps)
        dest = out_dir / f"f_{t_ms}.jpg"
        raw.rename(dest)
        frames.append(Frame(path=dest, t_ms=t_ms))
    return sorted(frames, key=lambda f: f.t_ms)


def extract_window_frames(video: Path, center_ms: int, out_dir: Path,
                        radius_ms: int = 1000, fps: float = 6.0) -> list[Frame]:
    """Full-resolution frames within ±``radius_ms`` of ``center_ms``.

    Used to hunt a sharper neighbour of the frame the picker chose; the
    files are named f_<t_ms>.jpg like the base frames.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    start_s = max(0.0, (center_ms - radius_ms) / 1000)
    end_s = (center_ms + radius_ms) / 1000
    _run(
        "ffmpeg",
        "-y", "-ss", str(start_s), "-to", str(end_s), "-i", str(video),
        "-vf", f"fps={fps}",
        "-q:v", "2",
        str(out_dir / "dense_%03d.jpg"),
    )
    frames = []
    for i, raw in enumerate(sorted(out_dir.glob("dense_*.jpg"))):
        t_ms = round(center_ms - radius_ms + i * 1000 / fps)
        dest = out_dir / f"f_{t_ms}.jpg"
        if dest.exists():
            dest = out_dir / f"f_{t_ms}_{i}.jpg"
        raw.rename(dest)
        frames.append(Frame(path=dest, t_ms=t_ms))
    return sorted(frames, key=lambda f: f.t_ms)


def cut_audio_clip(
    wav: Path, start_ms: int, end_ms: int, out: Path, pad_ms: int = 300
) -> Path:
    start_s = max(0.0, (start_ms - pad_ms) / 1000)
    end_s = (end_ms + pad_ms) / 1000
    _run(
        "ffmpeg",
        "-y", "-i", str(wav),
        "-ss", str(start_s), "-to", str(end_s),
        "-ac", "1", "-ar", str(AUDIO_SAMPLE_RATE),
        "-c:a", "aac",
        str(out),
    )
    return out
