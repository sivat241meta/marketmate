from __future__ import annotations

import subprocess
from pathlib import Path

from app.models import Frame


class VideoTooLong(Exception):
    pass


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([*args], check=True, capture_output=True, text=True)


def probe_duration_s(video: Path) -> float:
    result = _run(
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video),
    )
    return float(result.stdout.strip())


def check_length(video: Path, max_s: int) -> None:
    if probe_duration_s(video) > max_s:
        raise VideoTooLong(f"video is longer than {max_s}s")


def extract_audio(video: Path, out_wav: Path) -> Path:
    _run(
        "ffmpeg",
        "-y", "-i", str(video),
        "-ac", "1", "-ar", "16000", "-sample_fmt", "s16",
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


def cut_audio_clip(
    wav: Path, start_ms: int, end_ms: int, out: Path, pad_ms: int = 300
) -> Path:
    start_s = max(0.0, (start_ms - pad_ms) / 1000)
    end_s = (end_ms + pad_ms) / 1000
    _run(
        "ffmpeg",
        "-y", "-i", str(wav),
        "-ss", str(start_s), "-to", str(end_s),
        "-c:a", "aac",
        str(out),
    )
    return out
