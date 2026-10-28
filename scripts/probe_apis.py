"""Day-1 API probe: clip -> WAV -> transcribe -> Spark JSON -> frame -> Spark+SAM -> Baseten.

Usage: .venv/bin/python scripts/probe_apis.py eval/clips/synth1.mp4

Saves raw responses under tests/fixtures/ and prints, per call, HTTP status,
latency, token usage and estimated cost. API keys are read from the
environment (.env supported) and never printed.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from openai import OpenAI

META_BASE_URL = "https://api.meta.ai/v1"
BASETEN_BASE_URL = "https://inference.baseten.co/v1"
SPARK_MODEL = "muse-spark-1.3"
SPARK_OPEN_MODEL = "meta-models/muse-spark-open-1026"
VOICE_MODEL = "muse-voice-transcribe-1.0"
SAM_MODEL = "sam-3.1"

KEYWORDS = [
    "thakkali", "vengayam", "chinna vengayam", "urulaikizhangu", "carrot",
    "vazhaipazham", "thengai", "tomato", "onion", "potato", "banana", "coconut",
]

SPARK_USD_PER_1M_IN = 1.25
SPARK_USD_PER_1M_OUT = 4.25
TRANSCRIBE_USD_PER_HOUR = 0.18
SAM_USD_PER_CALL = 0.0025

FIXTURES = Path("tests/fixtures")
OUT = Path("eval/out")


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def spark_cost(prompt_tokens: int, completion_tokens: int) -> float:
    return prompt_tokens / 1e6 * SPARK_USD_PER_1M_IN + completion_tokens / 1e6 * SPARK_USD_PER_1M_OUT


def ffprobe_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(result.stdout.strip())


def main() -> None:
    clip = Path(sys.argv[1])
    load_dotenv()
    model_key = os.environ["MODEL_API_KEY"]
    baseten_key = os.environ.get("BASETEN_API_KEY", "")
    OUT.mkdir(parents=True, exist_ok=True)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    costs: dict[str, float] = {}

    wav = OUT / (clip.stem + ".wav")
    run(["ffmpeg", "-y", "-i", str(clip), "-ac", "1", "-ar", "24000",
         "-sample_fmt", "s16", str(wav)])
    audio_hours = ffprobe_duration(wav) / 3600

    request_payload = {
        "model": VOICE_MODEL,
        "audioEncoding": "WAV",
        "mode": "ENDPOINTING",
        "languageBias": ["Tamil", "English"],
        "keywords": KEYWORDS,
    }
    started = time.perf_counter()
    response = httpx.post(
        f"{META_BASE_URL}/asr/transcribe",
        files={
            "request": ("request.json", json.dumps(request_payload), "application/json"),
            "audio": (wav.name, wav.read_bytes(), "audio/wav"),
        },
        headers={"Authorization": "Bearer " + model_key},
        timeout=300,
    )
    latency = time.perf_counter() - started
    print(f"[transcribe] status={response.status_code} latency={latency:.1f}s")
    response.raise_for_status()
    transcribe_data = response.json()
    (FIXTURES / "transcribe_clip1.json").write_text(json.dumps(transcribe_data, indent=2))
    turns = transcribe_data.get("turns", [])
    text_len = len(transcribe_data.get("transcript", ""))
    print(f"[transcribe] turns={len(turns)} transcript_chars={text_len}")
    costs["transcribe"] = audio_hours * TRANSCRIBE_USD_PER_HOUR
    print(f"[transcribe] audio_hours={audio_hours:.4f} cost=${costs['transcribe']:.4f}")

    transcript_text = transcribe_data.get("transcript", "")
    text_prompt = ("The following is a transcript of a produce seller speaking "
                   "items and prices. List items and prices as JSON.\n\nTranscript:\n"
                   + transcript_text)
    meta_client = OpenAI(base_url=META_BASE_URL, api_key=model_key,
                         timeout=180.0, max_retries=2)
    started = time.perf_counter()
    spark_text = meta_client.chat.completions.create(
        model=SPARK_MODEL, max_tokens=4000,
        messages=[{"role": "user", "content": text_prompt}],
    )
    latency = time.perf_counter() - started
    usage = spark_text.usage
    (FIXTURES / "spark_text.json").write_text(spark_text.model_dump_json(indent=2))
    print(f"[spark-text] status=ok(SDK) latency={latency:.1f}s "
          f"prompt={usage.prompt_tokens} completion={usage.completion_tokens}")
    costs["spark-text"] = spark_cost(usage.prompt_tokens, usage.completion_tokens)
    print(f"[spark-text] cost=${costs['spark-text']:.4f}")

    frame = OUT / (clip.stem + "_frame5s.jpg")
    run(["ffmpeg", "-y", "-ss", "5", "-i", str(clip), "-frames:v", "1", str(frame)])
    data_url = "data:image/jpeg;base64," + base64.b64encode(frame.read_bytes()).decode()
    print(f"[frame] size_bytes={frame.stat().st_size} data_url_chars={len(data_url)}")
    image_prompt = ("What fruit or vegetable is shown in this photo? "
                    "Answer as JSON with keys name_en and confidence.")
    started = time.perf_counter()
    spark_image = meta_client.chat.completions.create(
        model=SPARK_MODEL, max_tokens=4000,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": image_prompt},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]}],
    )
    latency = time.perf_counter() - started
    usage = spark_image.usage
    (FIXTURES / "spark_image.json").write_text(spark_image.model_dump_json(indent=2))
    print(f"[spark-image] status=ok(SDK) latency={latency:.1f}s "
          f"prompt={usage.prompt_tokens} completion={usage.completion_tokens}")
    costs["spark-image"] = spark_cost(usage.prompt_tokens, usage.completion_tokens)
    print(f"[spark-image] cost=${costs['spark-image']:.4f}")

    sam_body = {
        "model": SAM_MODEL,
        "stream": True,
        "input": [{"role": "user", "content": [
            {"type": "input_text", "text": "tomato"},
            {"type": "input_image", "image_url": data_url},
        ]}],
    }
    started = time.perf_counter()
    chunks: list[str] = []
    sam_usage = "n/a"
    with httpx.stream("POST", f"{META_BASE_URL}/responses", json=sam_body,
                       headers={"Authorization": "Bearer " + model_key},
                       timeout=300) as sam_response:
        print(f"[sam] status={sam_response.status_code}")
        sam_response.raise_for_status()
        for line in sam_response.iter_lines():
            if not line.startswith("data:"):
                continue
            payload = line[len("data:"):].strip()
            if payload == "[DONE]":
                break
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "response.output_text.delta":
                chunks.append(event.get("delta", ""))
            if event.get("type") == "response.completed":
                response_usage = (event.get("response") or {}).get("usage")
                if response_usage:
                    sam_usage = json.dumps(response_usage)
                break
    latency = time.perf_counter() - started
    sam_text = "".join(chunks)
    (FIXTURES / "sam_frame.txt").write_text(sam_text)
    print(f"[sam] latency={latency:.1f}s output_chars={len(sam_text)} usage={sam_usage}")
    costs["sam"] = SAM_USD_PER_CALL
    print(f"[sam] cost=${costs['sam']:.4f}")

    baseten_client = OpenAI(base_url=BASETEN_BASE_URL, api_key=baseten_key,
                            timeout=180.0, max_retries=2)
    started = time.perf_counter()
    baseten_text = baseten_client.chat.completions.create(
        model=SPARK_OPEN_MODEL, max_tokens=4000,
        messages=[{"role": "user", "content": text_prompt}],
    )
    latency = time.perf_counter() - started
    usage = baseten_text.usage
    (FIXTURES / "baseten_text.json").write_text(baseten_text.model_dump_json(indent=2))
    print(f"[baseten-text] status=ok(SDK) latency={latency:.1f}s "
          f"prompt={usage.prompt_tokens} completion={usage.completion_tokens}")
    costs["baseten-text"] = 0.0
    print("[baseten-text] cost=$0.0000 (logged $0 against the Meta cap)")

    total = sum(costs.values())
    print(f"COSTS meta_meta={total:.4f} " + " ".join(f"{k}=${v:.4f}" for k, v in costs.items()))


if __name__ == "__main__":
    main()
