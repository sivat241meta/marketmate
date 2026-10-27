import json
from pathlib import Path

import pytest
from httpx import Response

from app.config import load_settings
from app.costs import CostCapExceeded, CostLedger
from app.meta.spark import SparkError, chat_json, image_part

_FIXTURE_BODY = json.loads(Path("tests/fixtures/spark_text.json").read_text())
_META_URL = "https://api.meta.ai/v1/chat/completions"
_BASETEN_URL = "https://inference.baseten.co/v1/chat/completions"


def make_body(content: str) -> dict:
    body = json.loads(json.dumps(_FIXTURE_BODY))
    body["choices"][0]["message"]["content"] = content
    return body


@pytest.fixture
def ledger(tmp_path):
    return CostLedger(tmp_path / "c.db", 100.0)


@pytest.fixture
def settings():
    return load_settings({"MODEL_API_KEY": "k"})


@pytest.fixture
def settings_baseten():
    return load_settings({
        "MODEL_API_KEY": "k",
        "BASETEN_API_KEY": "b",
        "TEXT_PROVIDER": "baseten",
    })


def test_chat_json_parses_fenced_json(respx_mock, ledger, settings):
    respx_mock.post(_META_URL).mock(
        return_value=Response(200, json=make_body('```json\n{"a":1}\n```')))
    assert chat_json([{"role": "user", "content": "hi"}],
                     ledger=ledger, settings=settings) == {"a": 1}
    assert ledger.today_usd() > 0


def test_chat_json_retries_once_then_raises(respx_mock, ledger, settings):
    route = respx_mock.post(_META_URL).mock(side_effect=[
        Response(200, json=make_body("not json")),
        Response(200, json=make_body("still not json")),
    ])
    with pytest.raises(SparkError):
        chat_json([{"role": "user", "content": "hi"}],
                  ledger=ledger, settings=settings)
    assert route.call_count == 2


def test_images_force_meta(respx_mock, ledger, settings_baseten, tmp_path):
    meta = respx_mock.post(_META_URL).mock(
        return_value=Response(200, json=make_body('{"a":1}')))
    baseten = respx_mock.post(_BASETEN_URL).mock(
        return_value=Response(200, json=make_body('{"a":1}')))
    frame = tmp_path / "f.jpg"
    frame.write_bytes(b"fakejpeg")
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "what is shown?"},
        image_part(frame),
    ]}]
    assert chat_json(messages, ledger=ledger, settings=settings_baseten) == {"a": 1}
    assert meta.call_count == 1
    assert baseten.call_count == 0


def test_baseten_text_logged_zero_usd(respx_mock, ledger, settings_baseten):
    respx_mock.post(_BASETEN_URL).mock(
        return_value=Response(200, json=make_body('{"a":1}')))
    assert chat_json([{"role": "user", "content": "hi"}],
                     ledger=ledger, settings=settings_baseten) == {"a": 1}
    assert ledger.today_usd("meta") == 0


def test_cap_checked_before_call(respx_mock, settings, tmp_path):
    ledger = CostLedger(tmp_path / "c.db", 0.01)
    ledger.add("meta", "muse-spark-1.3", 0.02)
    route = respx_mock.post(_META_URL).mock(
        return_value=Response(200, json=make_body('{"a":1}')))
    with pytest.raises(CostCapExceeded):
        chat_json([{"role": "user", "content": "hi"}],
                  ledger=ledger, settings=settings)
    assert route.call_count == 0
