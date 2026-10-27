import json
import sqlite3
from pathlib import Path

import pytest
from httpx import Response

from app.config import load_settings
from app.costs import CostCapExceeded, CostLedger, spark_cost
from app.meta.spark import SparkError, chat_json, image_part


def _length_body() -> dict:
    body = make_body("")
    body["choices"][0]["message"]["content"] = ""
    body["choices"][0]["finish_reason"] = "length"
    return body

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


def test_failed_attempts_still_logged(respx_mock, ledger, settings):
    route = respx_mock.post(_META_URL).mock(side_effect=[
        Response(200, json=make_body("not json at all")),
        Response(200, json=make_body("still not json")),
    ])
    with pytest.raises(SparkError):
        chat_json([{"role": "user", "content": "hi"}],
                  ledger=ledger, settings=settings)
    usage = _FIXTURE_BODY["usage"]
    expected = 2 * spark_cost({"prompt_tokens": usage["prompt_tokens"],
                               "completion_tokens": usage["completion_tokens"]})
    assert route.call_count == 2
    assert ledger.today_usd("meta") == pytest.approx(expected)


def test_length_cutoff_retries_with_doubled_budget(respx_mock, ledger, settings):
    route = respx_mock.post(_META_URL).mock(side_effect=[
        Response(200, json=_length_body()),
        Response(200, json=make_body('{"a":1}')),
    ])
    assert chat_json([{"role": "user", "content": "hi"}],
                     ledger=ledger, settings=settings) == {"a": 1}
    assert route.call_count == 2
    assert json.loads(route.calls[0].request.content)["max_tokens"] == 8000
    assert json.loads(route.calls[1].request.content)["max_tokens"] == 16000


def test_double_length_cutoff_raises(respx_mock, ledger, settings):
    route = respx_mock.post(_META_URL).mock(side_effect=[
        Response(200, json=_length_body()),
        Response(200, json=_length_body()),
    ])
    with pytest.raises(SparkError, match="cut off by max_tokens twice"):
        chat_json([{"role": "user", "content": "hi"}],
                  ledger=ledger, settings=settings)
    assert route.call_count == 2


def test_reasoning_effort_sent_to_meta(respx_mock, ledger, settings):
    route = respx_mock.post(_META_URL).mock(
        return_value=Response(200, json=make_body('{"a":1}')))
    assert chat_json([{"role": "user", "content": "hi"}],
                     ledger=ledger, settings=settings,
                     reasoning_effort="low") == {"a": 1}
    assert json.loads(route.calls[0].request.content)["reasoning_effort"] == "low"


def test_reasoning_effort_omitted_by_default(respx_mock, ledger, settings):
    route = respx_mock.post(_META_URL).mock(
        return_value=Response(200, json=make_body('{"a":1}')))
    chat_json([{"role": "user", "content": "hi"}],
              ledger=ledger, settings=settings)
    assert "reasoning_effort" not in json.loads(route.calls[0].request.content)


def test_reasoning_effort_sent_to_baseten(respx_mock, ledger, settings_baseten):
    route = respx_mock.post(_BASETEN_URL).mock(
        return_value=Response(200, json=make_body('{"a":1}')))
    assert chat_json([{"role": "user", "content": "hi"}],
                     ledger=ledger, settings=settings_baseten,
                     reasoning_effort="low") == {"a": 1}
    assert json.loads(route.calls[0].request.content)["reasoning_effort"] == "low"


def test_ledger_detail_records_budget_and_finish(respx_mock, ledger, settings,
                                                 tmp_path):
    respx_mock.post(_META_URL).mock(side_effect=[
        Response(200, json=_length_body()),
        Response(200, json=make_body('{"a":1}')),
    ])
    chat_json([{"role": "user", "content": "hi"}],
              ledger=ledger, settings=settings)
    rows = sqlite3.connect(tmp_path / "c.db").execute(
        "SELECT detail FROM costs ORDER BY id").fetchall()
    assert rows[0][0] == "chat_json max=8000 finish=length"
    assert rows[1][0] == "chat_json max=16000 finish=stop"


def test_length_cutoff_caps_doubled_budget(respx_mock, ledger, settings):
    route = respx_mock.post(_META_URL).mock(side_effect=[
        Response(200, json=_length_body()),
        Response(200, json=make_body('{"a":1}')),
    ])
    assert chat_json([{"role": "user", "content": "hi"}],
                     ledger=ledger, settings=settings, max_tokens=10000) == {"a": 1}
    assert json.loads(route.calls[1].request.content)["max_tokens"] == 16000


def test_cap_checked_before_call(respx_mock, settings, tmp_path):
    ledger = CostLedger(tmp_path / "c.db", 0.01)
    ledger.add("meta", "muse-spark-1.3", 0.02)
    route = respx_mock.post(_META_URL).mock(
        return_value=Response(200, json=make_body('{"a":1}')))
    with pytest.raises(CostCapExceeded):
        chat_json([{"role": "user", "content": "hi"}],
                  ledger=ledger, settings=settings)
    assert route.call_count == 0
