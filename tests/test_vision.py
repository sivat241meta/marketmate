"""Task 25: photo analysis engine (Spark vision + SAM counts, suggestions)."""

import json

import pytest
from httpx import Response

from app.config import load_settings
from app.costs import CostLedger
from app.meta.sam import find_boxes, parse_sam_text
from app.models import Box
from app.pipeline.vision import (
    MIN_BOX_CONFIDENCE,
    analyse_photo,
    dedupe_boxes,
    drop_low_confidence,
    list_products,
    reconcile,
)

_SAM_URL = "https://api.meta.ai/v1/responses"


@pytest.fixture
def ledger(tmp_path):
    return CostLedger(tmp_path / "c.db", 100.0)


@pytest.fixture
def settings():
    return load_settings({"MODEL_API_KEY": "k"})


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "stall.jpg"
    path.write_bytes(b"fakejpeg")
    return path


def make_box(x1, y1, x2, y2, confidence=None):
    return Box(x1, y1, x2, y2, 100, 100, confidence)


def row_boxes(n, confidence=None):
    """n equal side-by-side boxes that all survive dedupe."""
    return [Box(i * 10, 0, i * 10 + 8, 8, n * 10 + 10, 10, confidence)
            for i in range(n)]


# --- reconcile ---

def test_reconcile_both_none():
    assert reconcile(None, None) == (None, None, False)


def test_reconcile_one_none_uses_other():
    assert reconcile(5, None) == (5, None, False)
    assert reconcile(None, 7) == (7, None, False)


def test_reconcile_close_counts_agree():
    count, count_range, needs_check = reconcile(74, 75)
    assert count in (74, 75) and count_range is None and needs_check is False


def test_reconcile_far_counts_need_check():
    assert reconcile(24, 32) == (None, (24, 32), True)


def test_reconcile_boundary_is_inclusive():
    count, count_range, needs_check = reconcile(8, 10)
    assert (count, count_range, needs_check) == (9, None, False)


def test_reconcile_equal():
    assert reconcile(5, 5) == (5, None, False)


# --- dedupe_boxes ---

def test_dedupe_drops_tiny_box():
    boxes = [make_box(0, 0, 10, 10), make_box(20, 0, 30, 10),
             make_box(40, 0, 50, 10), make_box(60, 0, 61, 11)]
    kept = dedupe_boxes(boxes)
    assert len(kept) == 3
    assert all((b.x2 - b.x1) * (b.y2 - b.y1) == 100 for b in kept)


def test_dedupe_drops_nested_box():
    outer = make_box(0, 0, 10, 10)
    inner = make_box(1, 1, 9, 9)
    assert dedupe_boxes([outer, inner]) == [outer]


def test_dedupe_keeps_side_by_side():
    first = make_box(0, 0, 10, 10)
    second = make_box(20, 0, 30, 10)
    assert dedupe_boxes([first, second]) == [first, second]


def test_dedupe_keeps_small_overlap():
    first = make_box(0, 0, 10, 10)
    second = make_box(5, 0, 15, 10)
    assert dedupe_boxes([first, second]) == [first, second]


def test_dedupe_empty():
    assert dedupe_boxes([]) == []


# --- confidence filter ---

def test_min_box_confidence_is_point_eight():
    assert MIN_BOX_CONFIDENCE == 0.8


def test_confidence_filter_drops_low_keeps_high_and_none():
    low = make_box(0, 0, 5, 5, 0.5)
    high = make_box(10, 0, 15, 5, 0.85)
    unknown = make_box(20, 0, 25, 5, None)
    assert drop_low_confidence([low, high, unknown]) == [high, unknown]


# --- SAM confidence ---

def test_parse_sam_confidence():
    boxes = parse_sam_text("<|box;x1=1;y1=2;x2=11;y2=22;w=64;h=48;c=0.93|>")
    assert boxes[0].confidence == pytest.approx(0.93)


def test_parse_sam_confidence_absent_is_none():
    boxes = parse_sam_text("<|box;x1=1;y1=2;x2=11;y2=22;w=64;h=48|>")
    assert boxes[0].confidence is None


def test_sam_request_includes_confidence_metadata(respx_mock, ledger, settings,
                                                  tmp_path):
    token = "<|box;x1=1;y1=2;x2=11;y2=22;w=64;h=48;c=0.93|>"
    sse = (f'data: {{"type": "response.output_text.delta", "delta": "{token}"}}\n\n'
           'data: {"type": "response.completed", "response": {}}\n\n')
    route = respx_mock.post(_SAM_URL).mock(return_value=Response(200, text=sse))
    shot = tmp_path / "f.jpg"
    shot.write_bytes(b"fakejpeg")
    boxes = find_boxes(shot, "tomato", ledger=ledger, settings=settings)
    assert boxes[0].confidence == pytest.approx(0.93)
    sent = json.loads(route.calls[0].request.content)
    assert sent["metadata"] == {"include_confidence": "true",
                                "mask_encoding": "one_bit"}


# --- list_products ---

def _spark_reply():
    return {
        "products": [
            {"name_en": "shallot", "name_local": None, "countable": True,
             "visible_count": 27, "condition": "looks fresh"},
            {"name_en": "onion", "name_local": None, "countable": True,
             "visible_count": 1, "condition": None},
            {"name_en": "coriander", "name_local": None, "countable": False,
             "visible_count": None, "condition": None},
        ],
        "photo_quality": "dark",
    }


def test_list_products_single_low_vision_call(monkeypatch, image, ledger, settings):
    calls = []

    def fake_chat_json(messages, **kwargs):
        calls.append((messages, kwargs))
        return _spark_reply()

    monkeypatch.setattr("app.pipeline.vision.chat_json", fake_chat_json)
    products, quality = list_products(image, ledger=ledger, settings=settings)
    assert len(calls) == 1
    messages, kwargs = calls[0]
    assert kwargs.get("reasoning_effort") == "low"
    assert any(isinstance(part, dict) and part.get("type") == "image_url"
               for message in messages for part in message.get("content", [])
               if isinstance(message.get("content"), list))
    text = " ".join(str(part.get("text", ""))
                    for message in messages for part in message.get("content", [])
                    if isinstance(message.get("content"), list)
                    and isinstance(part, dict))
    assert "photo_quality" in text and "visible_count" in text
    assert quality == "dark"
    assert [(p["name_en"], p["countable"], p["visible_count"]) for p in products] == [
        ("shallot", True, 27), ("onion", True, 1), ("coriander", False, None)]
    assert products[0]["condition"] == "looks fresh"


def test_list_products_unknown_quality_becomes_good(monkeypatch, image, ledger,
                                                    settings):
    def fake_chat_json(messages, **kwargs):
        return {"products": [], "photo_quality": "foggy"}

    monkeypatch.setattr("app.pipeline.vision.chat_json", fake_chat_json)
    products, quality = list_products(image, ledger=ledger, settings=settings)
    assert (products, quality) == ([], "good")


def test_list_products_missing_keys_do_not_crash(monkeypatch, image, ledger,
                                                 settings):
    def fake_chat_json(messages, **kwargs):
        return {"products": [None, {}, {"name_en": None}]}

    monkeypatch.setattr("app.pipeline.vision.chat_json", fake_chat_json)
    products, quality = list_products(image, ledger=ledger, settings=settings)
    assert (products, quality) == ([], "good")


# --- analyse_photo ---

def _fake_sam(monkeypatch, boxes_by_noun, ledger):
    seen = []

    def fake_find_boxes(image, noun, **kwargs):
        seen.append(noun)
        ledger.add("meta", "sam-3.1", 0.0025, "test")
        return list(boxes_by_noun.get(noun, []))

    monkeypatch.setattr("app.pipeline.vision.find_boxes", fake_find_boxes)
    return seen


def _fake_spark(monkeypatch, reply, ledger):
    def fake_chat_json(messages, **kwargs):
        ledger.add("meta", "muse-spark-1.3", 0.01, "test")
        return reply

    monkeypatch.setattr("app.pipeline.vision.chat_json", fake_chat_json)


def test_analyse_photo_counts_and_suggestions(monkeypatch, image, ledger,
                                              settings):
    _fake_spark(monkeypatch, _spark_reply(), ledger)
    seen = _fake_sam(monkeypatch, {"shallot": row_boxes(31), "onion": row_boxes(1)},
                     ledger)
    shop_items = [{"name_en": "onion", "sold_out": True},
                  {"name_en": "coriander", "sold_out": False}]
    report = analyse_photo(image, shop_items=shop_items, ledger=ledger,
                           settings=settings)
    assert report.quality == "dark"
    assert "coriander" not in seen
    by_name = {p.name_en: p for p in report.products}
    shallot = by_name["shallot"]
    assert (shallot.count_spark, shallot.count_sam, shallot.count,
            shallot.count_range, shallot.needs_check) == (27, 31, 29, None, False)
    assert len(shallot.boxes) == 31
    assert shallot.condition == "looks fresh"
    assert by_name["onion"].count == 1
    assert by_name["coriander"].count is None
    assert by_name["coriander"].boxes == []
    assert [s.kind for s in report.suggestions] == [
        "retake", "add_price", "set_stock", "back_on_sale", "set_stock"]
    texts = {s.kind + ":" + (s.item_name or ""): s.text for s in report.suggestions}
    assert texts["retake:"] == "Photo looks dark. Take it again closer, in good light."
    assert "not on your price list" in texts["add_price:shallot"]
    assert report.suggestions[1].action == "voice_update"
    assert report.suggestions[2].value == 29
    assert report.suggestions[2].action == "set_stock"
    assert report.suggestions[3].action == "unsold"
    assert report.cost_usd == pytest.approx(0.01 + 2 * 0.0025)


def test_analyse_photo_disagreement_needs_check(monkeypatch, image, ledger,
                                                settings):
    reply = {"products": [{"name_en": "shallot", "name_local": None,
                           "countable": True, "visible_count": 24,
                           "condition": None}],
             "photo_quality": "good"}
    _fake_spark(monkeypatch, reply, ledger)
    _fake_sam(monkeypatch, {"shallot": row_boxes(32)}, ledger)
    report = analyse_photo(image, shop_items=[], ledger=ledger, settings=settings)
    (product,) = report.products
    assert (product.count, product.count_range, product.needs_check) == (
        None, (24, 32), True)
    check = [s for s in report.suggestions if s.kind == "check_count"]
    assert len(check) == 1
    assert check[0].text == "Shallot: we counted between 24 and 32. Please check."
    assert check[0].action == "set_stock" and check[0].value is None
    assert [s.kind for s in report.suggestions] == ["add_price", "check_count"]


def test_analyse_photo_synonym_matches_shop_item(monkeypatch, image, ledger,
                                                 settings):
    reply = {"products": [{"name_en": "shallot", "name_local": None,
                           "countable": True, "visible_count": 27,
                           "condition": None}],
             "photo_quality": "good"}
    _fake_spark(monkeypatch, reply, ledger)
    _fake_sam(monkeypatch, {"shallot": row_boxes(27)}, ledger)
    report = analyse_photo(
        image, shop_items=[{"name_en": "small onion", "sold_out": False}],
        ledger=ledger, settings=settings)
    assert [s.kind for s in report.suggestions] == ["set_stock"]


def test_analyse_photo_drops_low_confidence_boxes(monkeypatch, image, ledger,
                                                  settings):
    reply = {"products": [{"name_en": "onion", "name_local": None,
                           "countable": True, "visible_count": 1,
                           "condition": None}],
             "photo_quality": "good"}
    _fake_spark(monkeypatch, reply, ledger)
    boxes = [make_box(0, 0, 8, 8, 0.5), make_box(20, 0, 28, 8, 0.9)]
    _fake_sam(monkeypatch, {"onion": boxes}, ledger)
    report = analyse_photo(image, shop_items=[{"name_en": "onion",
                                               "sold_out": False}],
                           ledger=ledger, settings=settings)
    (product,) = report.products
    assert product.count_sam == 1 and product.count == 1


def test_analyse_photo_malformed_spark_json_does_not_crash(
        monkeypatch, image, ledger, settings):
    reply = {"products": [None, {},
                          {"name_en": None, "countable": True,
                           "visible_count": "lots"},
                          {"name_en": "  Tomato ", "condition": 42},
                          {"name_en": "mystery", "countable": "yes",
                           "visible_count": -3}],
             "photo_quality": "foggy"}
    _fake_spark(monkeypatch, reply, ledger)
    seen = _fake_sam(monkeypatch, {}, ledger)
    report = analyse_photo(image, shop_items=[], ledger=ledger, settings=settings)
    assert report.quality == "good"
    assert [p.name_en for p in report.products] == ["tomato", "mystery"]
    assert all(p.count is None and not p.needs_check for p in report.products)
    assert seen == []
    assert all(s.kind == "add_price" for s in report.suggestions)
