import pytest

from app.config import load_settings


def test_defaults():
    s = load_settings({"MODEL_API_KEY": "k"})
    assert s.text_provider == "meta" and s.daily_budget_usd == 3.0 and s.max_video_seconds == 180


def test_baseten_switch():
    s = load_settings({"MODEL_API_KEY": "k", "BASETEN_API_KEY": "b", "TEXT_PROVIDER": "baseten"})
    assert s.text_provider == "baseten"


def test_baseten_without_key_rejected():
    with pytest.raises(ValueError):
        load_settings({"MODEL_API_KEY": "k", "TEXT_PROVIDER": "baseten"})


def test_missing_meta_key_rejected():
    with pytest.raises(ValueError):
        load_settings({})
