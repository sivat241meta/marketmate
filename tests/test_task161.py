"""Task 161: picking a name on a "which item is it?" card names the price.

Live bug on Task 157's MISSED_PRICE card: tapping "beans" wrote an
input that does not exist, so the h2 stayed "other", collectCards kept
sending no name, and approve answered 400 forever. Now the option tap
renames the card's h2 from the glossary (the tick stays required) and
approve folds a renamed MISSED price into the same-named item as a
second line with the span's variety — prices never change. The live
fixture is Task 157's 17-card Tamil stall run (card 11 is the Mannur
₹70/kg line). No model calls.
"""

from __future__ import annotations

import json as jsonlib
from decimal import Decimal
from pathlib import Path

import test_task157
from test_task57 import create_shop, make_client, seed_review_session, token_of

from app import db

MISSED_INDEX = 11
BEANS_LOCAL = "பீன்ஸ்"


def live_payload() -> list[dict]:
    """The 17 live cards as the review form posts them."""
    return [jsonlib.loads(db._draft_to_json(item))
            for item in test_task157.items_b()]


def approve_live(tmp_path, body: list[dict], confirmed, removed=None):
    """Approve a live-like payload; returns (response, session_id, token)."""
    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    session_id = seed_review_session(tmp_path, token, test_task157.items_b())
    payload = {"items": body, "confirmed": list(confirmed)}
    if removed:
        payload["removed"] = list(removed)
    response = client.post(f"/e/{token}/s/{session_id}/approve",
                           json=payload)
    return response, session_id, token


def version_of(tmp_path):
    conn = db.connect(tmp_path / "data")
    try:
        shop_id = conn.execute("SELECT id FROM shops").fetchone()["id"]
        version_id = db.latest_version(conn, shop_id)
        return version_id, db.version_items(conn, version_id), shop_id
    finally:
        conn.close()


def test_named_beans_merges_as_second_price_line(tmp_path):
    body = live_payload()
    body[MISSED_INDEX]["name_spoken"] = "beans"
    body[MISSED_INDEX]["name_local"] = BEANS_LOCAL
    body[MISSED_INDEX]["name_en"] = "beans"
    response, _sid, _token = approve_live(
        tmp_path, body, confirmed=[1, 2, 3, MISSED_INDEX])
    assert response.status_code in (302, 303), response.text
    _version_id, version, shop_id = version_of(tmp_path)
    assert len(version) == 16
    assert all(item.name_en != "other" for item in version)
    beans = next(item for item in version if item.name_en == "beans")
    assert beans.name_local == BEANS_LOCAL
    assert beans.variety == "mannur"
    assert [(line.price, line.per_amount, line.unit)
            for line in beans.price_lines] == [
        (Decimal(35), Decimal("0.25"), "kg"),
        (Decimal(70), Decimal(1), "kg")]
    assert beans.price_lines[1].said == "எழுபது ஒரு கிலோ"
    assert "மன்னூர்ல" in beans.proof.quote
    assert 3 in beans.proof.turn_ids
    # Every other card is untouched, and no price anywhere changed.
    live = test_task157.items_b()
    names = [item.name_en for pos, item in enumerate(live)
             if pos != MISSED_INDEX]
    assert [item.name_en for item in version] == names
    want = sorted(((line.price, line.per_amount, line.unit)
                   for item in live for line in item.price_lines),
                  key=str)
    got = sorted(((line.price, line.per_amount, line.unit)
                  for item in version for line in item.price_lines),
                 key=str)
    assert got == want
    # The picked name is not a rename: match key "other" stays nameless.
    conn = db.connect(tmp_path / "data")
    try:
        assert db.chosen_name_for(conn, shop_id, "other", None) is None
    finally:
        conn.close()


def test_remove_still_drops_the_missed_card(tmp_path):
    body = live_payload()
    kept = [card for pos, card in enumerate(body)
            if pos != MISSED_INDEX]
    response, _sid, _token = approve_live(
        tmp_path, kept, confirmed=[1, 2, 3], removed=[MISSED_INDEX])
    assert response.status_code in (302, 303), response.text
    _version_id, version, _shop_id = version_of(tmp_path)
    assert len(version) == 16
    assert all(item.name_en != "other" for item in version)
    beans = next(item for item in version if item.name_en == "beans")
    assert len(beans.price_lines) == 1
    assert beans.price_lines[0].price == Decimal(35)


def test_unnamed_missed_still_needs_a_name(tmp_path):
    body = live_payload()
    response, _sid, _token = approve_live(
        tmp_path, body, confirmed=[1, 2, 3, MISSED_INDEX])
    assert response.status_code == 400
    payload = response.json()
    assert payload["detail"] == (
        "One price still needs a name — pick one or remove it.")
    assert payload["needs_confirm"][0]["index"] == MISSED_INDEX
    assert payload["needs_confirm"][0]["name"] == "other"


def test_unmatched_name_stays_its_own_item(tmp_path):
    body = live_payload()
    body[MISSED_INDEX]["name_spoken"] = "mango"
    body[MISSED_INDEX]["name_local"] = "மாம்பழம்"
    body[MISSED_INDEX]["name_en"] = "mango"
    response, _sid, _token = approve_live(
        tmp_path, body, confirmed=[1, 2, 3, MISSED_INDEX])
    assert response.status_code in (302, 303), response.text
    _version_id, version, shop_id = version_of(tmp_path)
    assert len(version) == 17
    assert all(item.name_en != "other" for item in version)
    mango = next(item for item in version if item.name_en == "mango")
    assert mango.name_local == "மாம்பழம்"
    assert mango.variety is None
    assert [(line.price, line.per_amount, line.unit)
            for line in mango.price_lines] == [
        (Decimal(70), Decimal(1), "kg")]
    assert mango.price_lines[0].said == "எழுபது ஒரு கிலோ"
    assert mango.proof.quote == test_task157.TURN_3_TEXT
    beans = next(item for item in version if item.name_en == "beans")
    assert len(beans.price_lines) == 1
    conn = db.connect(tmp_path / "data")
    try:
        assert db.chosen_name_for(conn, shop_id, "other", None) is None
    finally:
        conn.close()


def test_missed_option_buttons_carry_glossary_names(tmp_path):
    items = test_task157.items_b()
    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    session_id = seed_review_session(tmp_path, token, [items[10], items[11]])
    html = client.get(f"/e/{token}/s/{session_id}").text
    assert ('data-value="beans" data-name-local="பீன்ஸ்"'
            ' data-name-en="beans"') in html


def test_name_pick_renames_the_h2_in_the_browser():
    import shutil
    import subprocess

    node = shutil.which("node")
    assert node, "node is required"
    root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(["node", "tests/js/review_missed_name.test.mjs"],
                          cwd=root, check=False, capture_output=True,
                          text=True)
    assert proc.returncode == 0, proc.stderr + proc.stdout
