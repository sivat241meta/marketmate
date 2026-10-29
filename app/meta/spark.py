from __future__ import annotations

import base64
import json
from collections.abc import Callable
from pathlib import Path
from time import monotonic

from openai import OpenAI

from app.config import (
    BASETEN_BASE_URL,
    META_BASE_URL,
    SPARK_MODEL,
    SPARK_OPEN_MODEL,
    Settings,
)
from app.costs import CostLedger, spark_cost


class SparkError(Exception):
    pass


_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def image_part(path: Path) -> dict:
    """OpenAI image_url content part carrying the file as a data URL."""
    path = Path(path)
    mime = _MIME_TYPES.get(path.suffix.lower(), "image/jpeg")
    data = base64.b64encode(path.read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}


def _has_image(messages: list[dict]) -> bool:
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    return True
    return False


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines)
    return stripped


def _parse_first_json(text: str) -> dict:
    cleaned = _strip_fences(text)
    start = cleaned.find("{")
    if start < 0:
        raise SparkError("no JSON object in model reply")
    try:
        value, _ = json.JSONDecoder().raw_decode(cleaned[start:])
    except json.JSONDecodeError as exc:
        raise SparkError(f"invalid JSON in model reply: {exc}") from exc
    if not isinstance(value, dict):
        raise SparkError("model reply JSON is not an object")
    return value


def chat_json(
    messages: list[dict],
    *,
    ledger: CostLedger,
    settings: Settings,
    provider: str | None = None,
    max_tokens: int = 8000,
    reasoning_effort: str | None = None,
    step: str | None = None,
    shop_id: int | None = None,
    session_id: int | None = None,
    summary: str | Callable[[dict], str | None] | None = None,
) -> dict:
    """Chat via Muse Spark (Meta) or the Baseten open-weights mirror; parse JSON.

    reasoning_effort is passed to both providers when set (Baseten's
    OpenAI-compatible endpoint accepts it); an empty reply cut off by length
    escalates the token budget once to 16000 before giving up.
    ``summary`` is a fixed string or a function of the parsed reply; every
    attempt logs its own latency and ok flag.
    """
    ledger.check()
    wanted = provider or settings.text_provider
    if _has_image(messages):
        wanted = "meta"
    if wanted == "baseten":
        base_url, key, model = BASETEN_BASE_URL, settings.baseten_api_key, SPARK_OPEN_MODEL
        log_provider = "baseten"
    else:
        base_url, key, model = META_BASE_URL, settings.model_api_key, SPARK_MODEL
        log_provider = "meta"
    client = OpenAI(base_url=base_url, api_key=key, timeout=180.0, max_retries=2)
    budget = max_tokens
    current = list(messages)
    for attempt in (1, 2):
        started = monotonic()
        try:
            call: dict = {"model": model, "max_tokens": budget, "messages": current}
            if reasoning_effort is not None:
                call["reasoning_effort"] = reasoning_effort
            response = client.chat.completions.create(**call)
        except Exception as exc:
            ledger.add(log_provider, model, 0.0,
                       f"chat_json max={budget} finish=error",
                       shop_id=shop_id, session_id=session_id, step=step,
                       latency_ms=int((monotonic() - started) * 1000), ok=0)
            raise SparkError(f"Spark request failed: {exc}") from exc
        latency_ms = int((monotonic() - started) * 1000)
        choice = response.choices[0]
        finish = choice.finish_reason or "unknown"
        reply = choice.message.content or ""
        if finish == "length" and not reply.strip():
            _log_usage(ledger, log_provider, model, response.usage, budget,
                       finish, latency_ms, step, shop_id, session_id, None)
            if attempt == 2:
                raise SparkError("cut off by max_tokens twice")
            budget = min(budget * 2, 16000)
            continue
        try:
            data = _parse_first_json(reply)
        except SparkError:
            _log_usage(ledger, log_provider, model, response.usage, budget,
                       finish, latency_ms, step, shop_id, session_id, None)
            if attempt == 2:
                raise
            current = [*current,
                       {"role": "assistant", "content": reply},
                       {"role": "user", "content": "Return only valid JSON."}]
            continue
        _log_usage(ledger, log_provider, model, response.usage, budget,
                   finish, latency_ms, step, shop_id, session_id,
                   _render_summary(summary, data))
        return data
    raise SparkError("could not get JSON after retry")


def _render_summary(summary: str | Callable[[dict], str | None] | None,
                    data: dict) -> str | None:
    if summary is None or isinstance(summary, str):
        return summary
    try:
        return summary(data)
    except Exception:  # noqa: BLE001 - a bad summary never fails the call
        return None


def _log_usage(ledger: CostLedger, provider: str, model: str, usage,
               budget: int, finish: str, latency_ms: int,
               step: str | None, shop_id: int | None,
               session_id: int | None, summary: str | None) -> None:
    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
    completion_tokens = getattr(usage, "completion_tokens", 0) or 0
    if provider == "meta":
        usd = spark_cost({"prompt_tokens": prompt_tokens,
                          "completion_tokens": completion_tokens})
    else:
        usd = 0.0
    ledger.add(provider, model, usd, f"chat_json max={budget} finish={finish}",
               shop_id=shop_id, session_id=session_id, step=step,
               latency_ms=latency_ms, ok=1, summary=summary)
