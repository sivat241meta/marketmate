from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

META_BASE_URL = "https://api.meta.ai/v1"
BASETEN_BASE_URL = "https://inference.baseten.co/v1"
SPARK_MODEL = "muse-spark-1.3"
SPARK_OPEN_MODEL = "meta-models/muse-spark-open-1026"
VOICE_MODEL = "muse-voice-transcribe-1.0"
SAM_MODEL = "sam-3.1"


@dataclass(frozen=True)
class Settings:
    model_api_key: str
    baseten_api_key: str | None
    text_provider: str
    data_dir: Path
    daily_budget_usd: float
    max_video_seconds: int
    public_base_url: str
    uploads_per_ip_hour: int
    uploads_per_hour: int


def _get(env: Mapping[str, str], key: str, default: str) -> str:
    value = env.get(key, default)
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return default
    return value.strip() if isinstance(value, str) else value


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    if env is None:
        from dotenv import load_dotenv

        load_dotenv()
        env = dict(os.environ)

    raw_meta_key = env.get("MODEL_API_KEY", "")
    model_api_key = raw_meta_key.strip() if isinstance(raw_meta_key, str) else raw_meta_key
    if not model_api_key:
        raise ValueError("MODEL_API_KEY is required")

    text_provider = _get(env, "TEXT_PROVIDER", "meta").lower()
    if text_provider not in ("meta", "baseten"):
        raise ValueError("TEXT_PROVIDER must be 'meta' or 'baseten'")

    raw_baseten = env.get("BASETEN_API_KEY")
    if isinstance(raw_baseten, str):
        raw_baseten = raw_baseten.strip()
        baseten_api_key = raw_baseten if raw_baseten else None
    else:
        baseten_api_key = raw_baseten

    if text_provider == "baseten" and not baseten_api_key:
        raise ValueError("BASETEN_API_KEY is required when TEXT_PROVIDER=baseten")

    data_dir = Path(_get(env, "DATA_DIR", "./data"))

    try:
        daily_budget_usd = float(_get(env, "DAILY_BUDGET_USD", "3.0"))
    except ValueError as exc:
        raise ValueError("DAILY_BUDGET_USD must be a number") from exc

    try:
        max_video_seconds = int(_get(env, "MAX_VIDEO_SECONDS", "180"))
    except ValueError as exc:
        raise ValueError("MAX_VIDEO_SECONDS must be an integer") from exc

    public_base_url = _get(env, "PUBLIC_BASE_URL", "http://127.0.0.1:8000")

    try:
        uploads_per_ip_hour = int(_get(env, "UPLOADS_PER_IP_HOUR", "5"))
        uploads_per_hour = int(_get(env, "UPLOADS_PER_HOUR", "30"))
    except ValueError as exc:
        raise ValueError("upload limits must be integers") from exc

    return Settings(
        model_api_key=model_api_key,
        baseten_api_key=baseten_api_key,
        text_provider=text_provider,
        data_dir=data_dir,
        daily_budget_usd=daily_budget_usd,
        max_video_seconds=max_video_seconds,
        public_base_url=public_base_url,
        uploads_per_ip_hour=uploads_per_ip_hour,
        uploads_per_hour=uploads_per_hour,
    )
