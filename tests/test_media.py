import subprocess
import wave
from pathlib import Path

import pytest
from PIL import Image

from app.pipeline.media import (
    VideoTooLong,
    check_length,
    extract_audio,
    extract_frames,
    probe_duration_s,
)


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", *args], check=True, capture_output=True)


@pytest.fixture(scope="module")
def video_mp4(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("media") / "plain.mp4"
    _ffmpeg(
        "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(out),
    )
    return out


@pytest.fixture(scope="module")
def rotated_mp4(video_mp4: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("media") / "rotated.mp4"
    _ffmpeg("-display_rotation", "90", "-i", str(video_mp4), "-c", "copy", str(out))
    return out


@pytest.fixture(scope="module")
def video_webm(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("media") / "clip.webm"
    _ffmpeg(
        "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
        "-c:v", "libvpx-vp9", "-c:a", "libopus", "-shortest", str(out),
    )
    return out


def test_audio_is_16k_mono(tmp_path, video_mp4):
    wav = extract_audio(video_mp4, tmp_path / "a.wav")
    with wave.open(str(wav)) as f:
        assert f.getframerate() == 16000 and f.getnchannels() == 1


def test_two_frames_per_second(tmp_path, video_mp4):  # 3 s video
    frames = extract_frames(video_mp4, tmp_path)
    assert len(frames) == 6 and frames[1].t_ms == 500


def test_portrait_rotation_upright(tmp_path, rotated_mp4):  # 320x240 source, rotation 90
    f = extract_frames(rotated_mp4, tmp_path)[0]
    assert Image.open(f.path).size == (240, 320)


def test_webm_input(tmp_path, video_webm):
    assert extract_audio(video_webm, tmp_path / "a.wav").exists()


def test_too_long(video_mp4):
    with pytest.raises(VideoTooLong):
        check_length(video_mp4, 2)


def test_probe_duration_webm_without_metadata(tmp_path):
    out = tmp_path / "nodur.webm"
    with open(out, "wb") as f:
        subprocess.run(
            ["ffmpeg", "-y",
             "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=2",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
             "-c:v", "libvpx-vp9", "-c:a", "libopus",
             "-f", "webm", "pipe:1"],
            check=True, stdout=f, stderr=subprocess.DEVNULL,
        )
    assert probe_duration_s(out) == pytest.approx(2.0, abs=0.1)
