"""Task 33: language fixes from the live 23-language benchmark.

1. Tamil keyword bias: per-language Transcribe keywords.
2. Number cross-check must ask for the money amount only.
3. Canonical units everywhere.
4. Bengali/Marathi number sound-alikes + Mandarin/Thai unit sound-alikes.
5. Benchmark per-item detail, "What went wrong", --from-json mode.
"""

from __future__ import annotations

import json
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest

from app import db
from app.config import load_settings
from app.costs import CostLedger
from app.models import DraftItem, Flag, PriceLine, Proof, Transcript, Turn


def _settings(tmp_path):
    return load_settings({"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")})


def _draft(quote, price, said, unit="kg", per_amount=1, name_en="tomato"):
    return DraftItem(
        name_spoken=name_en, name_local=name_en, name_en=name_en,
        variety=None,
        price_lines=[PriceLine(Decimal(price), Decimal(per_amount), unit,
                              said)],
        qty=None, qty_unit=None,
        proof=Proof(quote=quote, turn_ids=[], start_ms=0, end_ms=0),
    )


def _ledger_settings(tmp_path):
    ledger = CostLedger(tmp_path / "c.db", 100.0)
    return ledger, load_settings({"MODEL_API_KEY": "k"})


# --- 1. Tamil keyword bias ---

def test_keywords_tamil_is_full_list():
    from app.pipeline.names import PRODUCE_KEYWORDS, keywords_for

    assert keywords_for("ta") == PRODUCE_KEYWORDS
    assert any("\u0b9a" in word for word in keywords_for("ta"))


def test_keywords_other_languages_have_no_tamil():
    from app.pipeline.names import keywords_for

    for code in ("vi", "bn", "kn", "fr", "en", "zh", "hi"):
        words = keywords_for(code)
        assert words, code
        for word in words:
            assert not any("\u0b80" <= ch <= "\u0bff" for ch in word), (code, word)
        for roman in ("thakkali", "vengayam", "vendaikkai", "kathirikkai",
                      "murungaikkai", "thengai"):
            assert roman not in words, (code, roman)
        assert "tomato" in words and "banana" in words, code


@pytest.fixture
def clip_mp4(tmp_path):
    out = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=1",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-shortest", str(out)],
        check=True, capture_output=True,
    )
    return out


def _canned_extract(monkeypatch):
    from app.models import Box

    def fake_chat_json(messages, **kwargs):
        content = messages[-1]["content"]
        if isinstance(content, list):
            content = " ".join(p.get("text", "") for p in content
                               if isinstance(p, dict))
        if "best shows" in content:
            return {"best_index": 0, "matches": True}
        return {"items": [{
            "name_spoken": "tomato", "name_en": "tomato", "variety": None,
            "prices": [{"said": "kilo 18", "price": 18, "per_amount": 1,
                        "unit": "kg"}],
            "range_said": False, "qty_said": None, "qty": None,
            "qty_unit": None, "turn_ids": [1], "quote": "tomato kilo 18"}]}

    monkeypatch.setattr("app.pipeline.extract.chat_json", fake_chat_json)
    monkeypatch.setattr("app.pipeline.frames.chat_json", fake_chat_json)
    monkeypatch.setattr("app.pipeline.photos.find_boxes",
                        lambda image, noun, **kw: [Box(10, 10, 50, 50, 320, 240, None)])


def test_run_passes_shop_language_keywords(tmp_path, clip_mp4, monkeypatch):
    from app.pipeline.names import keywords_for
    from app.pipeline.run import process_video_session

    _canned_extract(monkeypatch)
    seen = {}

    def fake_transcribe(wav, **kwargs):
        seen.update(kwargs)
        return Transcript(text="tomato kilo 18", duration_ms=1000, turns=[
            Turn(id=1, start_ms=0, end_ms=1000, text="tomato kilo 18")])

    monkeypatch.setattr("app.pipeline.run.transcribe_wav", fake_transcribe)
    settings = _settings(tmp_path)
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = db.create_shop(
            conn, name="VI", phone="+84111", area="A", language="vi",
            currency="VND", shop_type="vegetable")
        session_id = db.create_session(conn, shop_id, "video")
        ledger = CostLedger(tmp_path / "c.db", 100.0)
        process_video_session(conn, session_id, clip_mp4, settings=settings,
                              ledger=ledger)
    finally:
        conn.close()
    assert seen["keywords"] == keywords_for("vi")
    assert seen["languages"] == ("Vietnamese", "English")


def test_seller_update_passes_shop_language_keywords(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.pipeline.names import keywords_for
    from app.web.main import create_app

    settings = _settings(tmp_path)
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, token = db.create_shop(
            conn, name="FR", phone="+33111", area="A", language="fr",
            currency="EUR", shop_type="vegetable")
        session_id = db.create_session(conn, shop_id, "video")
        db.approve(conn, session_id, [_draft("tomato kilo 3", 3, "kilo 3")])
    finally:
        conn.close()
    seen = {}

    def fake_extract_audio(video, out_wav):
        Path(out_wav).parent.mkdir(parents=True, exist_ok=True)
        Path(out_wav).write_bytes(b"RIFF-fake-wav")
        return Path(out_wav)

    def fake_transcribe(wav, **kwargs):
        seen.update(kwargs)
        return Transcript(text="tomate 4", duration_ms=1000, turns=[
            Turn(id=1, start_ms=0, end_ms=1000, text="tomate 4")])

    monkeypatch.setattr("app.web.seller.extract_audio", fake_extract_audio)
    monkeypatch.setattr("app.web.seller.transcribe_wav", fake_transcribe)
    monkeypatch.setattr("app.pipeline.update.chat_json",
                        lambda messages, **kw: {"changes": []})
    response = TestClient(create_app(settings)).post(
        f"/e/{token}/update",
        files={"audio": ("update.webm", b"fake-opus", "audio/webm")})
    assert response.status_code == 200
    assert seen["keywords"] == keywords_for("fr")


def test_quote_voice_passes_shop_language_keywords(tmp_path, monkeypatch):
    from app.pipeline.names import keywords_for
    from app.web.quotes import process_quote_voice_session

    settings = _settings(tmp_path)
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = db.create_shop(
            conn, name="BN", phone="+880111", area="A", language="bn",
            currency="INR", shop_type="vegetable")
        session_id = db.create_session(conn, shop_id, "quote_voice")
    finally:
        pass
    seen = {}
    monkeypatch.setattr(
        "app.web.quotes.extract_audio",
        lambda video, out: Path(out).parent.mkdir(parents=True, exist_ok=True)
        or Path(out).write_bytes(b"RIFF") or Path(out))
    monkeypatch.setattr(
        "app.web.quotes.transcribe_wav",
        lambda wav, **kw: seen.update(kw) or Transcript(
            text="1 kg tomato", duration_ms=1000, turns=[
                Turn(id=1, start_ms=0, end_ms=1000, text="1 kg tomato")]))
    from app.market.search import parse_query_json

    monkeypatch.setattr(
        "app.market.quote.parse_query",
        lambda text, **kw: parse_query_json(
            {"wants": [{"name": "tomato", "amount": 1, "unit": "kg",
                        "max_rate": None}],
             "budget": None, "area": None}))
    conn = db.connect(tmp_path / "data")
    try:
        ledger = CostLedger(tmp_path / "c.db", 100.0)
        process_quote_voice_session(conn, session_id, tmp_path / "q.webm",
                                    settings=settings, ledger=ledger)
    finally:
        conn.close()
    assert seen["keywords"] == keywords_for("bn")


def test_bill_voice_passes_shop_language_keywords(tmp_path, monkeypatch):
    from app.pipeline.names import keywords_for
    from app.web.bills import process_bill_voice_session

    settings = _settings(tmp_path)
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = db.create_shop(
            conn, name="KN", phone="+91111", area="A", language="kn",
            currency="INR", shop_type="vegetable")
        session_id = db.create_session(conn, shop_id, "bill_voice")
    finally:
        pass
    seen = {}
    monkeypatch.setattr(
        "app.web.bills.extract_audio",
        lambda video, out: Path(out).parent.mkdir(parents=True, exist_ok=True)
        or Path(out).write_bytes(b"RIFF") or Path(out))
    monkeypatch.setattr(
        "app.web.bills.transcribe_wav",
        lambda wav, **kw: seen.update(kw) or Transcript(
            text="1 kg tomato", duration_ms=1000, turns=[
                Turn(id=1, start_ms=0, end_ms=1000, text="1 kg tomato")]))
    from app.market.search import parse_query_json

    monkeypatch.setattr(
        "app.market.quote.parse_query",
        lambda text, **kw: parse_query_json(
            {"wants": [{"name": "tomato", "amount": 1, "unit": "kg",
                        "max_rate": None}],
             "budget": None, "area": None}))
    conn = db.connect(tmp_path / "data")
    try:
        ledger = CostLedger(tmp_path / "c.db", 100.0)
        process_bill_voice_session(conn, session_id, tmp_path / "b.webm",
                                   settings=settings, ledger=ledger)
    finally:
        conn.close()
    assert seen["keywords"] == keywords_for("kn")


# --- 2. number cross-check asks for the price ---

def test_cross_check_price_key_agrees(tmp_path, monkeypatch):
    from app.pipeline import checks as checks_mod
    from app.pipeline.checks import check_item

    ledger, settings = _ledger_settings(tmp_path)
    seen = {}

    def fake_chat_json(messages, **kwargs):
        seen["messages"] = messages
        return {"price": 4}

    monkeypatch.setattr(checks_mod, "chat_json", fake_chat_json)
    item = _draft("banana, une douzaine, quatre euros", 4,
                  "une douzaine, quatre euros", unit="dozen",
                  name_en="banana")
    flags = check_item(item, {}, language="fr", ledger=ledger,
                       settings=settings)
    assert "NUMBER_CHECK" not in [f.code for f in flags]
    assert "NOT_HEARD" not in [f.code for f in flags]
    assert item.proof.number_check == "cross-checked"


def test_cross_check_prompt_mentions_price_quantity_and_currency(tmp_path,
                                                               monkeypatch):
    from app.pipeline import checks as checks_mod
    from app.pipeline.checks import check_item

    ledger, settings = _ledger_settings(tmp_path)
    seen = {}
    monkeypatch.setattr(
        checks_mod, "chat_json",
        lambda messages, **kw: seen.setdefault("m", messages) or {"price": 4})
    item = _draft("banana, une douzaine, quatre euros", 4,
                  "une douzaine, quatre euros", unit="dozen",
                  name_en="banana")
    check_item(item, {}, language="fr", ledger=ledger, settings=settings)
    blob = json.dumps(seen["m"]).lower()
    assert "price" in blob and "quantity" in blob
    assert "euro" in blob  # registry currency hint for French


def test_cross_check_value_key_still_accepted(tmp_path, monkeypatch):
    from app.pipeline import checks as checks_mod
    from app.pipeline.checks import check_item

    ledger, settings = _ledger_settings(tmp_path)
    monkeypatch.setattr(checks_mod, "chat_json",
                        lambda messages, **kw: {"value": 40})
    item = _draft("tomate quarante euros", 40, "quarante")
    flags = check_item(item, {}, language="fr", ledger=ledger,
                       settings=settings)
    assert "NUMBER_CHECK" not in [f.code for f in flags]
    assert item.proof.number_check == "cross-checked"


# --- 3. canonical units ---

KILO_WORDS = ["kilo", "kilogram", "kg", "킬로", "キロ", "公斤", "กิโล", "ký",
              "cân", "kilogramo", "quilo", "chilo", "Kilo", "kilogramme",
              "किलो", "কেজি", "கிலோ", "కిలో", "ಕಿಲೋ", "كيلو", "קילו"]
PIECE_WORDS = ["piece", "pc", "pcs", "unit", "each", "no.", "nos", "개", "個",
               "个", "只", "ลูก", "อัน", "trái", "quả", "buah", "biji",
               "sztuka", "sztukę", "pièce", "Stück", "pezzo", "unidad",
               "unidade", "stuk", "adet", "tane", "piraso", "पीस", "নগ",
               "টা", "ஒன்று"]
DOZEN_WORDS = ["dozen", "doz", "다스", "打", "ダース", "โหล", "tá", "lusin",
               "tuzin", "douzaine", "Dutzend", "dozzina", "docena", "dúzia",
               "dozijn", "düzine", "dosena", "दर्जन", "ডজন", "டஜன்",
               "డజను", "ಡಜನ್", "درزن", "תריסר"]
BUNCH_WORDS = ["bunch", "kattu", "கட்டு", "गुच्छा", "束", "把"]
GRAM_WORDS = ["g", "gram", "gramme", "grams", "ग्राम", "கிராம்"]


@pytest.mark.parametrize("word", KILO_WORDS)
def test_normalize_kilo_family(word):
    from app.pipeline.units import normalize_unit

    assert normalize_unit(word) == ("kg", Decimal(1))


@pytest.mark.parametrize("word", PIECE_WORDS)
def test_normalize_piece_family(word):
    from app.pipeline.units import normalize_unit

    assert normalize_unit(word) == ("piece", Decimal(1))


@pytest.mark.parametrize("word", DOZEN_WORDS)
def test_normalize_dozen_family(word):
    from app.pipeline.units import normalize_unit

    assert normalize_unit(word) == ("dozen", Decimal(1))


@pytest.mark.parametrize("word", BUNCH_WORDS)
def test_normalize_bunch_family(word):
    from app.pipeline.units import normalize_unit

    assert normalize_unit(word) == ("bunch", Decimal(1))


@pytest.mark.parametrize("word", GRAM_WORDS)
def test_normalize_gram_family(word):
    from app.pipeline.units import normalize_unit

    assert normalize_unit(word) == ("g", Decimal(1))


def test_normalize_jin_scales_to_half_kg():
    from app.pipeline.units import normalize_unit

    assert normalize_unit("斤") == ("kg", Decimal("0.5"))


def test_normalize_liang_scales_to_50g():
    from app.pipeline.units import normalize_unit

    assert normalize_unit("两") == ("g", Decimal(50))


def test_normalize_unknown_returns_none():
    from app.pipeline.units import normalize_unit

    assert normalize_unit("scoop") == (None, Decimal(1))
    assert normalize_unit("") == (None, Decimal(1))
    assert normalize_unit(None) == (None, Decimal(1))


def test_price_line_jin_scales_per_amount():
    from app.pipeline.units import normalize_price_line

    line = PriceLine(Decimal(8), Decimal(2), "斤", "两斤八块")
    normalize_price_line(line)
    assert (line.per_amount, line.unit) == (Decimal(1), "kg")


def test_unknown_unit_keeps_raw_and_flags_unit_check():
    from app.pipeline.checks import check_item

    item = _draft("tomato scoop 18", 18, "scoop 18", unit="scoop")
    flags = {f.code: f for f in check_item(item, {})}
    assert "UNIT_CHECK" in flags
    assert flags["UNIT_CHECK"].blocking is False
    assert flags["UNIT_CHECK"].message == "please check the unit"
    assert item.price_lines[0].unit == "scoop"


def test_canonical_unit_has_no_unit_check():
    from app.pipeline.checks import check_item

    item = _draft("tomato kilo 18", 18, "kilo 18", unit="kg")
    assert "UNIT_CHECK" not in [f.code for f in check_item(item, {})]


def test_extract_prompt_demands_canonical_units():
    from app.pipeline.extract import build_extract_messages

    content = build_extract_messages(
        Transcript(text="t", duration_ms=1,
                   turns=[Turn(id=1, start_ms=0, end_ms=1, text="t")])
    )[-1]["content"]
    for unit in ("kg", "g", "l", "ml", "piece", "dozen", "bunch", "packet"):
        assert unit in content


def test_parse_extract_normalizes_heard_units():
    from app.pipeline.extract import parse_extract_json

    transcript = Transcript(text="t", duration_ms=1, turns=[
        Turn(id=1, start_ms=0, end_ms=1, text="t")])
    items = parse_extract_json({"items": [{
        "name_spoken": "coconut", "name_en": "coconut", "variety": None,
        "prices": [{"said": "1 pc 5", "price": 5, "per_amount": 1,
                    "unit": "pc"}],
        "range_said": False, "qty": None, "qty_unit": None, "turn_ids": [1],
        "quote": "t"}]}, transcript, language="fr")
    assert items[0].price_lines[0].unit == "piece"


def test_benchmark_price_rate_normalizes_units():
    from scripts.benchmark import price_rate

    assert price_rate(5, 1, "pc") == price_rate(5, 1, "piece")
    assert price_rate(8, 2, "斤") == price_rate(8, 1, "kg")
    assert price_rate(5, 1, "scoop") is None


def test_quote_text_path_normalizes_units():
    from app.market.search import parse_query_json

    query = parse_query_json(
        {"wants": [{"name": "tomato", "amount": 2, "unit": "pcs",
                    "max_rate": None}],
         "budget": None, "area": None})
    assert (query.wants[0].amount, query.wants[0].unit) == (Decimal(2),
                                                            "piece")


def test_quote_photo_path_normalizes_units():
    from app.market.quote import _photo_unit

    assert _photo_unit("pcs") == "piece"
    assert _photo_unit("kilo") == "kg"


# --- 4. sound-alikes ---

def test_bengali_sixty_seven_sound_alike():
    from app.pipeline.checks import check_item

    item = _draft("kola shaat taka", 60, "shaat", unit="dozen",
                  name_en="banana")
    flag = next(f for f in check_item(item, {}, language="bn")
                if f.code == "SOUND_ALIKE")
    assert set(flag.options) == {"7", "60"}
    assert "Bengali" in flag.message


def test_bengali_sixty_seven_script():
    from app.pipeline.checks import check_item

    item = _draft("কলা ষাট টাকা", 60, "ষাট", unit="dozen", name_en="banana")
    assert any(f.code == "SOUND_ALIKE"
               for f in check_item(item, {}, language="bn"))
    item2 = _draft("কলা সাত টাকা", 7, "সাত", unit="dozen", name_en="banana")
    flag = next(f for f in check_item(item2, {}, language="bn")
                if f.code == "SOUND_ALIKE")
    assert set(flag.options) == {"7", "60"}


def test_marathi_sixty_seven_sound_alike():
    from app.pipeline.checks import check_item

    item = _draft("kela saath rupaye", 60, "saath", unit="dozen",
                  name_en="banana")
    flag = next(f for f in check_item(item, {}, language="mr")
                if f.code == "SOUND_ALIKE")
    assert set(flag.options) == {"7", "60"}
    assert "Marathi" in flag.message


def test_mandarin_dozen_bunch_unit_sound_alike():
    from app.pipeline.checks import check_item

    item = _draft("香蕉，一扎，十二块钱", 12, "一扎十二块", unit="dozen",
                  name_en="banana")
    flag = next(f for f in check_item(item, {}, language="zh")
                if f.code == "SOUND_ALIKE" and f.field == "unit")
    assert flag.options == ["dozen", "bunch"]
    assert flag.blocking is True


def test_mandarin_correct_dozen_has_no_unit_flag():
    from app.pipeline.checks import check_item

    item = _draft("香蕉，一打，十二块钱", 12, "一打十二块", unit="dozen",
                  name_en="banana")
    assert not [f for f in check_item(item, {}, language="zh")
                if f.code == "SOUND_ALIKE" and f.field == "unit"]


def test_thai_dozen_kilo_unit_sound_alike():
    from app.pipeline.checks import check_item

    item = _draft("กล้วยหนึ่งโลห้าสิบบาท", 50, "หนึ่งโลห้าสิบ",
                  unit="dozen", name_en="banana")
    flag = next(f for f in check_item(item, {}, language="th")
                if f.code == "SOUND_ALIKE" and f.field == "unit")
    assert flag.options == ["dozen", "kg"]
    assert flag.blocking is True


def test_thai_real_kilo_has_no_unit_flag():
    from app.pipeline.checks import check_item

    item = _draft("มะเขือเทศหนึ่งกิโลสี่สิบบาท", 40, "หนึ่งกิโลสี่สิบ",
                  unit="kg", name_en="tomato")
    assert not [f for f in check_item(item, {}, language="th")
                if f.code == "SOUND_ALIKE" and f.field == "unit"]


def test_review_renders_unit_option_buttons(tmp_path):
    import re

    from fastapi.testclient import TestClient

    from app.pipeline.names import CANONICAL_NAMES
    from app.web.main import create_app

    settings = _settings(tmp_path)
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, token = db.create_shop(
            conn, name="ZH", phone="+86111", area="A", language="zh",
            currency="CNY", shop_type="vegetable")
        item = _draft("香蕉，一扎，十二块钱", 12, "一扎十二块", unit="dozen",
                      name_en="banana")
        item.name_local = CANONICAL_NAMES["banana"]
        item.flags.append(Flag(field="unit", code="SOUND_ALIKE",
                               message="did you say dozen or bunch?",
                               options=["dozen", "bunch"]))
        session_id = db.create_session(conn, shop_id, "video")
        db.save_drafts(conn, session_id, [item])
        db.set_session_status(conn, session_id, "review", "needs review")
    finally:
        conn.close()
    html = TestClient(create_app(settings)).get(
        f"/e/{token}/s/{session_id}").text
    buttons = re.findall(r"<button[^>]*class=\"[^\"]*opt-btn[^\"]*\"[^>]*>",
                         html)
    unit_buttons = [b for b in buttons if "data-target-field=\"unit\"" in b]
    assert len(unit_buttons) == 2
    assert all("data-field" not in b for b in unit_buttons)
    assert 'data-value="dozen"' in unit_buttons[0]
    assert 'data-value="bunch"' in unit_buttons[1]


# --- 5. benchmark detail ---

def _lang_key_out():
    key = {"clip": "hi.mp4", "items": [
        {"name_en": "banana", "price": 60, "per_amount": 1, "unit": "dozen",
         "expect_flags": []},
        {"name_en": "coconut", "price": 25, "per_amount": 1, "unit": "piece",
         "expect_flags": []},
    ]}
    out = {"clip": "hi.mp4", "items": [{
        "name_en": "banana",
        "price_lines": [{"price": "7", "per_amount": "1", "unit": "dozen"}],
        "flags": [{"code": "SOUND_ALIKE", "message": "did you say 7 or 60?",
                   "options": ["7", "60"], "blocking": True}],
        "proof": {"quote": "केला एक दर्जन सात रुपए"},
    }]}
    return key, out


def test_detail_items_carry_want_got_flags_quote():
    from scripts.lang_benchmark import detail_items

    key, out = _lang_key_out()
    detail = detail_items(key, out)
    assert [d["name_en"] for d in detail] == ["banana", "coconut"]
    banana = detail[0]
    assert banana["want"] == {"price": 60, "per_amount": 1, "unit": "dozen"}
    assert banana["got"] == [{"price": "7", "per_amount": "1",
                              "unit": "dozen"}]
    assert banana["flags"][0]["options"] == ["7", "60"]
    assert "सात" in banana["quote"]
    assert banana["verdict"] == "flagged"
    assert detail[1]["verdict"] == "missed"
    assert detail[1]["got"] == []


def test_notes_flagged_only_vs_needs_work():
    from scripts.lang_benchmark import notes_for

    assert notes_for({"status": "tested", "found": 4, "exact": 3,
                      "flagged": 1, "wrong_unflagged": 0,
                      "missed": 0}) == "flagged only"
    assert notes_for({"status": "tested", "found": 4, "exact": 3,
                      "flagged": 0, "wrong_unflagged": 1,
                      "missed": 0}) == "needs work"
    assert notes_for({"status": "tested", "found": 3, "exact": 3,
                      "flagged": 0, "wrong_unflagged": 0,
                      "missed": 1}) == "needs work"
    assert notes_for({"status": "tested", "found": 4, "exact": 4,
                      "flagged": 0, "wrong_unflagged": 0,
                      "missed": 0}) == "ok"


def test_render_explains_wrong_unflagged_and_lists_misses():
    from scripts.lang_benchmark import detail_items, render_languages_md

    key, out = _lang_key_out()
    results = [{
        "code": "hi", "api_name": "Hindi", "native_name": "हिन्दी",
        "voice": "Lekha", "status": "tested", "in_key": 2, "found": 1,
        "exact": 0, "flagged": 1, "wrong_unflagged": 0, "missed": 1,
        "cost_usd": 0.05, "seconds": 35.0,
        "transcript": "केला एक दर्जन सात रुपए",
        "items": detail_items(key, out),
    }]
    md = render_languages_md(results, provider="meta")
    assert "wrong-unflagged\" means a wrong price or unit shown with no warning" in md
    assert "## What went wrong" in md
    assert "Hindi - banana: heard 7 instead of 60" in md
    assert "flagged: did you say 7 or 60?" in md
    assert "Hindi - coconut: not in the transcript" in md


def test_from_json_rebuilds_md_without_network(tmp_path, monkeypatch):
    import scripts.lang_benchmark as bench

    key, out = _lang_key_out()
    saved = {
        "provider": "meta",
        "results": [{
            "code": "hi", "api_name": "Hindi", "native_name": "हिन्दी",
            "voice": "Lekha", "status": "tested", "in_key": 2, "found": 1,
            "exact": 0, "flagged": 1, "wrong_unflagged": 0, "missed": 1,
            "cost_usd": 0.05, "seconds": 35.0,
            "transcript": "केला एक दर्जन सात रुपए",
            "items": bench.detail_items(key, out),
        }],
    }
    out_json = tmp_path / "lang_results.json"
    out_md = tmp_path / "languages.md"
    out_json.write_text(json.dumps(saved))
    monkeypatch.setattr(bench, "OUT_JSON", out_json)
    monkeypatch.setattr(bench, "DOC_PATH", out_md)
    monkeypatch.setattr("sys.argv", ["lang_benchmark.py", "--from-json"])

    def no_network(*args, **kwargs):
        raise AssertionError("must not touch the network")

    monkeypatch.setattr("httpx.post", no_network)
    monkeypatch.setattr("httpx.get", no_network)
    bench.main()
    md = out_md.read_text()
    assert "## What went wrong" in md
    assert "Hindi - banana: heard 7 instead of 60" in md
