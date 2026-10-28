"""Make one synthetic test clip per language that has a macOS `say` voice.

Usage: .venv/bin/python scripts/make_lang_clips.py [--only ta,hi,...]

For each language in eval/lang/scripts.json, finds a macOS voice whose
locale equals voice_locale (first match in `say -v '?'` output). Each of
the 4 sentences is spoken with `say -v VOICE -o part.aiff` and paired
with its photo (scaled/padded to 720x1280 portrait, white background)
for the length of its audio. Segments are joined with ffmpeg concat.

Outputs (eval/clips is git-ignored):
  eval/clips/lang/{code}.mp4
  eval/clips/lang/{code}.answers.json  (same format as eval/answers/*.json)

Prints a table: code, voice, seconds, status. No network calls.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_PATH = ROOT / "eval" / "lang" / "scripts.json"
OUT_DIR = ROOT / "eval" / "clips" / "lang"
PHOTO_ORDER = ["tomato", "onion", "banana", "coconut"]

_SAY_LINE_RE = re.compile(r"^(.*?)\s+([A-Za-z]{2,3}_[A-Za-z0-9]+)\s+#")


def load_scripts(path: Path | None = None) -> dict:
    """Parsed eval/lang/scripts.json."""
    return json.loads(Path(path or SCRIPTS_PATH).read_text())


def select_voice(say_output: str, locale: str) -> str | None:
    """First voice in `say -v '?'` output whose locale equals `locale`."""
    for line in say_output.splitlines():
        match = _SAY_LINE_RE.search(line)
        if match and match.group(2) == locale:
            return match.group(1).strip()
    return None


def split_sentences(text: str, expected: int = 4) -> list[str]:
    """Split test text into `expected` sentences.

    Splits on [.。।!?]+; when that does not yield `expected` parts
    (e.g. Thai has no sentence punctuation), falls back to splitting
    whitespace-separated words into `expected` equal chunks in order.
    """
    parts = [p.strip() for p in re.split(r"[.。।!?]+", text) if p.strip()]
    if len(parts) == expected:
        return parts
    words = text.split()
    if not words:
        return []
    base, rem = divmod(len(words), expected)
    chunks: list[str] = []
    idx = 0
    for i in range(expected):
        size = base + (1 if i < rem else 0)
        if size <= 0:
            break
        chunks.append(" ".join(words[idx : idx + size]))
        idx += size
    if len(chunks) != expected:
        return parts if parts else [text.strip()]
    return chunks


def build_say_cmd(voice: str, text: str, out: Path) -> list[str]:
    """`say -v VOICE -o part.aiff` for one sentence."""
    return ["say", "-v", voice, "-o", str(out), text]


def build_segment_cmd(photo: Path, audio: Path, out: Path) -> list[str]:
    """Still photo for the length of its audio, 720x1280 portrait on white."""
    vf = (
        "scale=720:1280:force_original_aspect_ratio=decrease,"
        "pad=720:1280:(ow-iw)/2:(oh-ih)/2:white"
    )
    return [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(photo),
        "-i", str(audio),
        "-vf", vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-shortest", str(out),
    ]


def build_concat_cmd(list_file: Path, out: Path) -> list[str]:
    """Join per-sentence segments with the ffmpeg concat demuxer."""
    return [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy", str(out),
    ]


def answers_for(code: str, entry: dict) -> dict:
    """Answer key in the same format as eval/answers/*.json."""
    items = [
        {
            "name_en": ans["name_en"],
            "variety": None,
            "price": ans["price"],
            "per_amount": ans["per_amount"],
            "unit": ans["unit"],
            "qty": None,
            "qty_unit": None,
            "expect_flags": ["QTY_MISSING"],
        }
        for ans in entry["answers"]
    ]
    return {
        "clip": f"{code}.mp4",
        "note": (
            "Synthetic test: macOS voice + Wikimedia photos. "
            "Prices are local-currency test values, not real market data."
        ),
        "items": items,
    }


def _say_voices() -> str:
    try:
        proc = subprocess.run(
            ["say", "-v", "?"], check=False, capture_output=True, text=True
        )
    except OSError:
        return ""
    return (proc.stdout or "") + (proc.stderr or "")


def _probe_seconds(video: Path) -> float:
    from app.pipeline.media import probe_duration_s

    try:
        return float(probe_duration_s(video))
    except Exception:  # noqa: BLE001 - duration is best-effort for the table
        return 0.0


def _make_one(code: str, entry: dict, photos: dict, voice: str) -> tuple[float, str]:
    sentences = split_sentences(entry["text"])
    if len(sentences) != 4:
        return 0.0, f"bad script ({len(sentences)} sentences)"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_mp4 = OUT_DIR / f"{code}.mp4"
    try:
        with tempfile.TemporaryDirectory(prefix=f"lang_{code}_") as tmp:
            tmpdir = Path(tmp)
            seg_paths: list[Path] = []
            for i, (sentence, key) in enumerate(zip(sentences, PHOTO_ORDER)):
                photo = ROOT / photos[key]
                if not photo.is_file():
                    return 0.0, f"missing photo {key}"
                aiff = tmpdir / f"part{i}.aiff"
                try:
                    proc = subprocess.run(
                        build_say_cmd(voice, sentence, aiff),
                        check=False, capture_output=True, text=True,
                        timeout=180,
                    )
                except subprocess.TimeoutExpired:
                    return 0.0, "say timed out"
                if proc.returncode != 0 or not aiff.is_file():
                    err = (proc.stderr or "").strip().splitlines()
                    detail = f": {err[0]}" if err else ""
                    return 0.0, f"say failed{detail}"
                if _probe_seconds(aiff) <= 0:
                    return 0.0, "say produced no audio"
                seg = tmpdir / f"seg{i}.mp4"
                try:
                    proc = subprocess.run(
                        build_segment_cmd(photo, aiff, seg),
                        check=False, capture_output=True, text=True,
                        timeout=300,
                    )
                except subprocess.TimeoutExpired:
                    return 0.0, "ffmpeg segment timed out"
                if proc.returncode != 0 or not seg.is_file():
                    return 0.0, "ffmpeg segment failed"
                seg_paths.append(seg)
            lst = tmpdir / "concat.txt"
            lst.write_text("".join(f"file '{p}'\n" for p in seg_paths))
            try:
                proc = subprocess.run(
                    build_concat_cmd(lst, out_mp4),
                    check=False, capture_output=True, text=True,
                    timeout=300,
                )
            except subprocess.TimeoutExpired:
                return 0.0, "ffmpeg concat timed out"
            if proc.returncode != 0 or not out_mp4.is_file():
                return 0.0, "ffmpeg concat failed"
        answers = answers_for(code, entry)
        (OUT_DIR / f"{code}.answers.json").write_text(json.dumps(answers, indent=2))
        return _probe_seconds(out_mp4), "ok"
    except OSError as exc:
        return 0.0, f"failed: {exc}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="")
    args = parser.parse_args()
    only = {c.strip() for c in args.only.split(",") if c.strip()} or None

    data = load_scripts()
    photos = data["photos"]
    say_output = _say_voices()

    rows: list[tuple[str, str, float, str]] = []
    for code in sorted(data["languages"]):
        if only and code not in only:
            continue
        entry = data["languages"][code]
        voice = select_voice(say_output, entry["voice_locale"])
        if voice is None:
            rows.append((code, "-", 0.0, "no test voice"))
            continue
        seconds, status = _make_one(code, entry, photos, voice)
        rows.append((code, voice, seconds, status))

    print("| code | voice | seconds | status |")
    print("|---|---|---|---|")
    for code, voice, seconds, status in rows:
        print(f"| {code} | {voice} | {seconds:.1f} | {status} |")


if __name__ == "__main__":
    main()
