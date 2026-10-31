"""Task 97: a known variety decides the item.

On the owner's real vegetable video the seller said only the variety for two
brinjal lines ("ujala", "vari krishnagiri vari") and Spark carried the
previous noun (carrot, ooty) forward. After extraction the variety wins:
those drafts become brinjal before photo selection, with a soft note on the
check page. No network: canned Spark JSON plus stubbed photo/audio steps.
"""

from __future__ import annotations

from decimal import Decimal

from app import db
from app.config import load_settings
from app.costs import CostLedger
from app.models import DraftItem, Frame, PriceLine, Proof, Transcript, Turn
from app.pipeline.extract import parse_extract_json

CANNED_VEGETABLES = {"items": [
    {"name_spoken": "beans", "name_en": "beans", "variety": None,
     "prices": [{"said": "kilo forty", "price": 40,
                "per_amount": 1, "unit": "kg"}],
     "range_said": False, "qty_said": None, "qty": None, "qty_unit": None,
     "turn_ids": [1], "quote": "beans kilo forty"},
    {"name_spoken": "ooty carrot", "name_en": "carrot", "variety": "ooty",
     "prices": [{"said": "kilo thirty", "price": 30,
                "per_amount": 1, "unit": "kg"}],
     "range_said": False, "qty_said": None, "qty": None, "qty_unit": None,
     "turn_ids": [2], "quote": "ooty carrot kilo thirty"},
    {"name_spoken": "avaraikkai", "name_en": "broad beans", "variety": None,
     "prices": [{"said": "kilo fifty", "price": 50,
                "per_amount": 1, "unit": "kg"}],
     "range_said": False, "qty_said": None, "qty": None, "qty_unit": None,
     "turn_ids": [3], "quote": "avaraikkai kilo fifty"},
    {"name_spoken": "ujala", "name_en": "carrot", "variety": "ujala",
     "prices": [{"said": "kilo sixty", "price": 60,
                "per_amount": 1, "unit": "kg"}],
     "range_said": False, "qty_said": None, "qty": None, "qty_unit": None,
     "turn_ids": [4], "quote": "ujala kilo sixty"},
    {"name_spoken": "வரி krishnagiri வரி", "name_en": "carrot",
     "variety": "krishnagiri",
     "prices": [{"said": "kilo seventy", "price": 70,
                "per_amount": 1, "unit": "kg"}],
     "range_said": False, "qty_said": None, "qty": None, "qty_unit": None,
     "turn_ids": [5], "quote": "வரி krishnagiri வரி kilo seventy"},
]}


def _transcript() -> Transcript:
    texts = ["beans kilo forty", "ooty carrot kilo thirty",
             "avaraikkai kilo fifty", "ujala kilo sixty",
             "வரி krishnagiri வரி kilo seventy"]
    turns = [Turn(id=i + 1, start_ms=i * 3000, end_ms=(i + 1) * 3000,
                  text=text) for i, text in enumerate(texts)]
    return Transcript(text=" ".join(texts), duration_ms=15000, turns=turns)


def _drafts():
    from app.pipeline.names import correct_draft_from_variety

    items = parse_extract_json(CANNED_VEGETABLES, _transcript(), language="ta")
    for item in items:
        correct_draft_from_variety(item, language="ta")
    return items


def test_variety_decides_item_exact_case():
    items = _drafts()
    assert [i.name_en for i in items] == [
        "beans", "carrot", "broad beans", "brinjal", "brinjal"]
    assert [i.match_key for i in items] == [
        "beans", "carrot", "broad beans", "brinjal", "brinjal"]
    assert items[3].name_local == "கத்திரிக்காய்"
    assert items[4].name_local == "கத்திரிக்காய்"
    assert items[3].variety == "ujala"
    assert items[4].variety == "krishnagiri"
    # The ooty carrot keeps its noun and variety.
    assert items[1].variety == "ooty"
    assert items[1].name_local == "கேரட்"


def test_prices_and_proof_untouched():
    items = _drafts()
    assert items[3].price_lines[0].price == Decimal(60)
    assert items[3].price_lines[0].said == "kilo sixty"
    assert items[3].proof.quote == "ujala kilo sixty"
    assert items[3].proof.turn_ids == [4]
    assert items[4].price_lines[0].price == Decimal(70)
    assert items[4].proof.quote == "வரி krishnagiri வரி kilo seventy"


def test_check_page_note_text():
    from app.web.i18n import flag_text

    items = _drafts()
    notes = [f for f in items[3].flags if f.code == "VARIETY_NAMED"]
    assert len(notes) == 1
    assert not notes[0].blocking
    assert flag_text(notes[0], "en") == (
        "Named from the variety you said (ujala → brinjal)")
    notes = [f for f in items[4].flags if f.code == "VARIETY_NAMED"]
    assert len(notes) == 1
    assert flag_text(notes[0], "en") == (
        "Named from the variety you said (krishnagiri → brinjal)")
    for item in items[:3]:
        assert [f for f in item.flags if f.code == "VARIETY_NAMED"] == []


def _draft(name_en, variety=None, spoken="", quote=""):
    return DraftItem(
        name_spoken=spoken or name_en, name_local=name_en, name_en=name_en,
        variety=variety, match_key=name_en,
        price_lines=[PriceLine(Decimal(10), Decimal(1), "kg")],
        qty=None, qty_unit=None,
        proof=Proof(quote=quote or spoken or name_en, turn_ids=[1],
                    start_ms=0, end_ms=1000),
    )


def test_same_item_variety_fills():
    from app.pipeline.names import correct_draft_from_variety

    item = _draft("banana", None, "poovan pazham", "poovan pazham dozen sixty")
    flag = correct_draft_from_variety(item, language="ta")
    assert flag is None
    assert item.name_en == "banana"
    assert item.variety == "poovan"
    assert item.flags == []


def test_current_item_mentioned_blocks_rename():
    from app.pipeline.names import correct_draft_from_variety

    # "pachai" is a banana (green) alias, but the line names green chilli.
    item = _draft("green chilli", None, "pachai milagaai",
                  "pachai milagaai kilo thirty")
    assert correct_draft_from_variety(item, language="ta") is None
    assert item.name_en == "green chilli"
    assert item.variety is None
    # Ooty is a carrot alias, but the line names a potato.
    item = _draft("potato", "ooty", "ooty potato", "ooty potato kilo forty")
    assert correct_draft_from_variety(item, language="ta") is None
    assert item.name_en == "potato"


def test_spoken_alias_without_variety_renames():
    from app.pipeline.names import correct_draft_from_variety

    item = _draft("carrot", None, "ujala", "ujala kilo sixty")
    flag = correct_draft_from_variety(item, language="ta")
    assert flag is not None
    assert item.name_en == "brinjal"
    assert item.variety == "ujala"
    assert item.name_local == "கத்திரிக்காய்"


def _conn(tmp_path):
    conn = db.connect(tmp_path)
    shop_id, _, _ = db.create_shop(
        conn, name="T97 Stall", phone="+914400000097", area="Koyambedu",
        language="ta", currency="INR", shop_type="vegetable")
    return conn, shop_id


def _process_settings(tmp_path):
    return load_settings({"MODEL_API_KEY": "k",
                          "DATA_DIR": str(tmp_path / "data")})


def _stub_photo_path(monkeypatch, nouns):
    from app.pipeline import run as run_mod

    def fake_pick(item, candidates, **kwargs):
        return (candidates[0], True)

    def fake_window(frames, picked, **kwargs):
        return [picked]

    def fake_candidates(pool, frame, noun, prefix, **kwargs):
        nouns.append(noun)
        return []

    monkeypatch.setattr(run_mod, "pick_best_frame", fake_pick)
    monkeypatch.setattr(run_mod, "window_frames", fake_window)
    monkeypatch.setattr(run_mod, "make_candidates", fake_candidates)
    monkeypatch.setattr(run_mod, "check_item", lambda *a, **k: [])
    monkeypatch.setattr(run_mod, "cut_audio_clip",
                        lambda wav, start, end, dest: dest)


def test_photo_noun_is_brinjal(tmp_path, monkeypatch):
    from app.pipeline import run as run_mod

    conn, shop_id = _conn(tmp_path)
    session_id = db.create_session(conn, shop_id, "video")
    nouns: list[str] = []
    _stub_photo_path(monkeypatch, nouns)
    transcript = _transcript()
    monkeypatch.setattr(
        run_mod, "extract_items",
        lambda *a, **k: parse_extract_json(CANNED_VEGETABLES, transcript,
                                           language="ta"))
    frames = [Frame(path=tmp_path / f"f_{ms}.jpg", t_ms=ms)
              for ms in range(0, 15000, 500)]
    settings = _process_settings(tmp_path)
    ledger = CostLedger(tmp_path / "costs.db", 10.0)
    run_mod.process_turns(conn, session_id, transcript.turns, None,
                          tmp_path / "audio.wav", settings=settings,
                          ledger=ledger, language="ta", all_frames=frames,
                          video=None)
    # Task 140: the photo work runs concurrently, so invocations land in
    # completion order; the names themselves (brinjal, not ujala) match.
    assert sorted(nouns) == ["beans", "brinjal", "brinjal", "broad beans",
                             "carrot"]
    drafts = db.load_drafts(conn, session_id)
    assert [d.name_en for d in drafts] == ["beans", "carrot", "broad beans",
                                          "brinjal", "brinjal"]


def test_seller_chosen_name_never_overridden(tmp_path, monkeypatch):
    from app.pipeline import run as run_mod

    conn, shop_id = _conn(tmp_path)
    db.save_chosen_name(conn, shop_id, "carrot", "ujala",
                        "செல்ல கேரட்", "seller carrot")
    session_id = db.create_session(conn, shop_id, "video")
    nouns: list[str] = []
    _stub_photo_path(monkeypatch, nouns)
    canned = {"items": [CANNED_VEGETABLES["items"][3]]}
    transcript = _transcript()
    monkeypatch.setattr(
        run_mod, "extract_items",
        lambda *a, **k: parse_extract_json(canned, transcript, language="ta"))
    frames = [Frame(path=tmp_path / f"f_{ms}.jpg", t_ms=ms)
              for ms in range(0, 15000, 500)]
    settings = _process_settings(tmp_path)
    ledger = CostLedger(tmp_path / "costs.db", 10.0)
    run_mod.process_turns(conn, session_id, transcript.turns, None,
                          tmp_path / "audio.wav", settings=settings,
                          ledger=ledger, language="ta", all_frames=frames,
                          video=None)
    drafts = db.load_drafts(conn, session_id)
    assert drafts[0].name_en == "seller carrot"
    assert drafts[0].name_local == "செல்ல கேரட்"
    assert drafts[0].match_key == "carrot"
    assert [f for f in drafts[0].flags if f.code == "VARIETY_NAMED"] == []


def test_board_path_corrects(tmp_path, monkeypatch):
    from app.pipeline import board as board_mod

    conn, shop_id = _conn(tmp_path)
    session_id = db.create_session(conn, shop_id, "board")
    monkeypatch.setattr(
        board_mod, "chat_json",
        lambda *a, **k: {"lines": [
            {"name_as_written": "ujala", "name_en": "carrot",
             "name_local": None, "price": 60, "read": "60",
             "per_amount": 1, "unit": "kg"},
            {"name_as_written": "poovan", "name_en": "banana",
             "name_local": None, "price": 70, "read": "70",
             "per_amount": 1, "unit": "dozen"},
        ]})
    monkeypatch.setattr("app.pipeline.checks.check_item",
                        lambda *a, **k: [])
    settings = _process_settings(tmp_path)
    ledger = CostLedger(tmp_path / "costs.db", 10.0)
    (tmp_path / "board.jpg").write_bytes(b"fake-board-photo")
    board_mod.process_board_session(conn, session_id, tmp_path / "board.jpg",
                                    settings=settings, ledger=ledger)
    drafts = db.load_drafts(conn, session_id)
    assert drafts[0].name_en == "brinjal"
    assert drafts[0].name_local == "கத்திரிக்காய்"
    assert [f for f in drafts[0].flags if f.code == "VARIETY_NAMED"]
    assert drafts[1].name_en == "banana"
    assert drafts[1].variety == "poovan"


def _current_item(name_en, variety=None, local=None, match_key=None):
    from app.models import Item

    return Item(
        id=0, version_id=0, name_local=local or name_en, name_en=name_en,
        variety=variety, qty=None, qty_unit=None, photo=None, sold_out=False,
        price_lines=[PriceLine(Decimal(10), Decimal(1), "kg")],
        proof=Proof(quote=name_en, turn_ids=[], start_ms=0, end_ms=0),
        match_key=match_key or name_en,
    )


def _update_transcript():
    turn = Turn(id=1, start_ms=0, end_ms=3000, text="ujala kilo sixty")
    return Transcript(text="ujala kilo sixty", duration_ms=3000, turns=[turn])


def test_update_path_corrects():
    from app.pipeline.update import parse_update_json

    current = [_current_item("carrot", local="கேரட்"),
               _current_item("brinjal", local="கத்திரிக்காய்")]
    data = {"changes": [
        {"name_en": "carrot", "action": "set_price",
         "prices": [{"said": "sixty", "price": 60,
                    "per_amount": 1, "unit": "kg"}],
         "qty": None, "qty_unit": None, "turn_ids": [1],
         "quote": "ujala kilo sixty"},
    ]}
    (change,) = parse_update_json(data, _update_transcript(), current,
                                   language="ta")
    assert change.name_en == "brinjal"
    assert [f for f in change.flags if f.code == "VARIETY_NAMED"]


def test_update_path_keeps_seller_renamed_item():
    from app.pipeline.update import parse_update_json

    current = [_current_item("seller carrot", local="செல்ல கேரட்",
                             match_key="carrot")]
    data = {"changes": [
        {"name_en": "carrot", "action": "set_price",
         "prices": [{"said": "sixty", "price": 60,
                    "per_amount": 1, "unit": "kg"}],
         "qty": None, "qty_unit": None, "turn_ids": [1],
         "quote": "ujala kilo sixty"},
    ]}
    (change,) = parse_update_json(data, _update_transcript(), current,
                                   language="ta")
    assert change.name_en == "carrot"
    assert [f for f in change.flags if f.code == "VARIETY_NAMED"] == []


def test_update_path_current_item_mentioned_blocks_rename():
    from app.pipeline.update import parse_update_json

    current = [_current_item("green chilli", local="பச்சை மிளகாய்")]
    data = {"changes": [
        {"name_en": "green chilli", "action": "set_price",
         "prices": [{"said": "thirty", "price": 30,
                    "per_amount": 1, "unit": "kg"}],
         "qty": None, "qty_unit": None, "turn_ids": [1],
         "quote": "pachai milagaai kilo thirty"},
    ]}
    turn = Turn(id=1, start_ms=0, end_ms=3000,
                text="pachai milagaai kilo thirty")
    transcript = Transcript(text=turn.text, duration_ms=3000, turns=[turn])
    (change,) = parse_update_json(data, transcript, current, language="ta")
    assert change.name_en == "green chilli"
