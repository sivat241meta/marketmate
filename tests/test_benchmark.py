from scripts.benchmark import compare_clips, normalize_variety


def test_normalize_variety():
    assert normalize_variety("Bangalore") == normalize_variety("bengaluru")
    assert normalize_variety(None) is None
    assert normalize_variety("  ") is None


def test_benchmark_counts():
    key = {"clip": "t.mp4", "items": [
        {"name_en": "Tomato", "variety": "Bengaluru", "price": 18,
         "per_amount": 1, "unit": "kg", "qty": None, "qty_unit": None,
         "expect_flags": []},
        {"name_en": "Potato", "variety": None, "price": 35,
         "per_amount": 1, "unit": "kg", "qty": None, "qty_unit": None,
         "also_said": [30], "expect_flags": ["TWO_PRICES"]},
        {"name_en": "Onion", "variety": None, "price": 25,
         "per_amount": 1, "unit": "kg", "qty": None, "qty_unit": None,
         "expect_flags": ["SOUND_ALIKE"]},
    ]}
    out = {"clip": "t.mp4", "items": [
        {"name_en": "tomato", "variety": "bengaluru",
         "price_lines": [{"price": "18", "per_amount": "1",
                          "unit": "kg", "said": "kilo 18"}],
         "flags": []},
        {"name_en": "potato", "variety": None,
         "price_lines": [{"price": "30", "per_amount": "1",
                          "unit": "kg", "said": "kilo 30"},
                         {"price": "35", "per_amount": "1",
                          "unit": "kg", "said": "thirty five"}],
         "flags": [{"code": "TWO_PRICES", "blocking": True,
                    "message": "x", "options": ["30", "35"]}]},
        {"name_en": "onion", "variety": None,
         "price_lines": [{"price": "25", "per_amount": "1",
                          "unit": "kg", "said": "25"}],
         "flags": []},
    ]}
    row = compare_clips(key, out)
    assert (row["in_key"], row["found"], row["exact"]) == (3, 3, 2)
    assert row["flagged"] == 1 and row["unflagged"] == 0
    assert row["raised"] == {"TWO_PRICES": 1}
    assert row["missed"] == {"SOUND_ALIKE": 1}


def test_benchmark_rate_equality():
    key = {"clip": "t.mp4", "items": [
        {"name_en": "Carrot", "variety": None, "price": 15,
         "per_amount": 250, "unit": "g", "qty": None, "qty_unit": None,
         "expect_flags": []},
    ]}
    out = {"clip": "t.mp4", "items": [
        {"name_en": "carrot", "variety": None,
         "price_lines": [{"price": "15", "per_amount": "0.25",
                          "unit": "kg", "said": "quarter kilo 15"}],
         "flags": []},
    ]}
    row = compare_clips(key, out)
    assert (row["exact"], row["flagged"], row["unflagged"]) == (1, 0, 0)


def test_null_variety_matches_any_variety():
    key = {"clip": "t.mp4", "items": [
        {"name_en": "Onion", "variety": None, "price": 25,
         "per_amount": 1, "unit": "kg", "qty": None, "qty_unit": None,
         "expect_flags": ["QTY_MISSING"]},
    ]}
    out = {"clip": "t.mp4", "items": [
        {"name_en": "onion", "variety": "big",
         "price_lines": [{"price": "25", "per_amount": "1",
                          "unit": "kg", "said": "big onion 25"}],
         "flags": [{"code": "QTY_MISSING", "blocking": False,
                    "message": "x", "options": []}]},
    ]}
    row = compare_clips(key, out)
    assert (row["found"], row["exact"]) == (1, 1)
    assert row["raised"] == {"QTY_MISSING": 1}
    assert row["missed"] == {}


def test_rerun_baseten_runs_honesty_checks(tmp_path, monkeypatch):
    import json
    from decimal import Decimal

    from app.models import DraftItem, PriceLine, Proof
    from scripts import benchmark

    monkeypatch.setenv("MODEL_API_KEY", "k")
    monkeypatch.setenv("BASETEN_API_KEY", "b")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))

    def fake_extract(transcript, *, ledger, settings):
        return [DraftItem(
            name_spoken="potato", name_local="உருளைக்கிழங்கு", name_en="potato",
            variety=None,
            price_lines=[PriceLine(Decimal(30), Decimal(1), "kg", "thirty"),
                         PriceLine(Decimal(35), Decimal(1), "kg", "thirty five")],
            qty=None, qty_unit=None,
            proof=Proof(quote="potato thirty rupees thirty five rupees",
                        turn_ids=[1], start_ms=0, end_ms=1000),
        )]

    monkeypatch.setattr(benchmark, "extract_items", fake_extract)
    out_path = tmp_path / "t.json"
    out_path.write_text(json.dumps({
        "clip": "t.mp4", "shop_id": 1, "items": [],
        "transcript": {"text": "potato", "duration_ms": 1000, "turns": [
            {"id": 1, "start_ms": 0, "end_ms": 1000, "text": "potato"}]},
    }))
    target = benchmark._rerun_baseten(out_path)
    rerun = json.loads(target.read_text())
    rerun_codes = [f["code"] for f in rerun["items"][0]["flags"]]
    assert "TWO_PRICES" in rerun_codes
    assert "QTY_MISSING" in rerun_codes
