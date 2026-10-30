"""Task 18: judge try-it mode, upload limits, expiry purge, demo seeding."""

import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from starlette.requests import Request

from app import db
from app.config import load_settings
from app.costs import CostCapExceeded, CostLedger
from app.limits import RateLimiter, client_ip
from app.market.search import Query, Want, find_listings
from app.models import DraftItem, Flag, PriceLine, Proof
from app.pipeline.run import process_video_session
from app.web.main import create_app
from scripts import seed_demo

JUDGE_BANNER = "Test shop - not listed in the market, deleted after 7 days"
BUDGET_MSG = "Today's demo budget is used up - please try the sample shops."


def make_settings(tmp_path, **overrides):
    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    env.update(overrides)
    return load_settings(env)


def make_client(tmp_path, monkeypatch, settings=None):
    settings = settings or make_settings(tmp_path)
    app = create_app(settings)

    def fake_submit(fn, *args):
        fn(*args)

    def fake_process(conn, session_id, video, *, settings, ledger):
        db.save_drafts(conn, session_id, [clean_draft()])
        db.set_session_status(conn, session_id, "review", "1 item needs review")

    monkeypatch.setattr("app.web.seller.jobs.submit", fake_submit)
    monkeypatch.setattr("app.web.seller.process_video_session", fake_process)
    return TestClient(app, follow_redirects=False)


def clean_draft():
    return DraftItem(
        name_spoken="tomato",
        name_local="தக்காளி",
        name_en="tomato",
        variety=None,
        price_lines=[PriceLine(Decimal(18), Decimal(1), "kg", "kilo 18")],
        qty=None,
        qty_unit=None,
        proof=Proof(quote="tomato kilo 18", turn_ids=[1], start_ms=0, end_ms=1000),
        flags=[Flag(field="qty", code="QTY_MISSING", message="no quantity",
                    blocking=False)],
    )


def create_shop(client, name="Kannan Store"):
    response = client.post("/new", data={
        "name": name, "phone": "+914400000000", "area": "Koyambedu",
        "language": "ta", "currency": "INR", "type": "vegetable"})
    assert response.status_code in (302, 303)
    return response.headers["location"]


def post_upload(client, seller_url, filename="clip.mp4"):
    return client.post(seller_url + "/upload",
                       files={"video": (filename, b"fakevideo", "video/mp4")})


def draft_dict(name_en, name_local, price, flags=(), photo=None):
    item = DraftItem(
        name_spoken=name_en, name_local=name_local, name_en=name_en, variety=None,
        price_lines=[PriceLine(Decimal(price), Decimal(1), "kg",
                               f"kilo {price}")],
        qty=None, qty_unit=None,
        proof=Proof(quote=f"{name_en} kilo {price}", turn_ids=[1],
                    start_ms=0, end_ms=1000),
        flags=list(flags), photo=photo)
    return json.loads(db._draft_to_json(item))


def write_run_json(path, items):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "clip": "clip1.mp4", "shop_id": 1, "session_id": 1,
        "status": "review", "message": "2 items need review",
        "transcript": None, "items": items, "meta_usd": 0.12}))
    return path


def backdate(path, days):
    old = (datetime.now(UTC) - timedelta(days=days)).timestamp()
    os.utime(path, (old, old))


# --- RateLimiter unit tests ---

def test_limiter_per_ip_cap():
    limiter = RateLimiter(per_ip_hour=5, global_hour=30)
    now = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    assert all(limiter.allow("1.1.1.1", now) for _ in range(5))
    assert not limiter.allow("1.1.1.1", now)
    assert limiter.allow("2.2.2.2", now)


def test_limiter_global_cap():
    limiter = RateLimiter(per_ip_hour=5, global_hour=3)
    now = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    assert limiter.allow("a", now)
    assert limiter.allow("b", now)
    assert limiter.allow("c", now)
    assert not limiter.allow("d", now)


def test_limiter_resets_each_hour():
    limiter = RateLimiter(per_ip_hour=1, global_hour=10)
    start = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    assert limiter.allow("ip", start)
    assert not limiter.allow("ip", start + timedelta(minutes=59))
    assert limiter.allow("ip", start + timedelta(minutes=61))


# --- Upload rate limiting ---

def test_sixth_upload_from_one_ip_returns_429(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    seller_url = create_shop(client)
    for _ in range(5):
        assert post_upload(client, seller_url).status_code in (302, 303)
    denied = post_upload(client, seller_url)
    assert denied.status_code == 429
    assert "text/html" in denied.headers["content-type"]
    assert "Too many uploads" in denied.text


# --- Proxy-aware client IP (task 19) ---

def make_request(headers=None, host="9.9.9.9"):
    raw = [(k.lower().encode("latin-1"), v.encode("latin-1"))
           for k, v in (headers or {}).items()]
    scope = {"type": "http", "method": "POST", "headers": raw,
             "client": (host, 5000) if host is not None else None}
    return Request(scope)


def test_client_ip_prefers_first_forwarded_address():
    request = make_request({"x-forwarded-for": "1.2.3.4, 10.0.0.1"})
    assert client_ip(request) == "1.2.3.4"


def test_client_ip_falls_back_to_client_host():
    assert client_ip(make_request()) == "9.9.9.9"


def test_client_ip_blank_header_falls_back_to_client_host():
    assert client_ip(make_request({"x-forwarded-for": "   "})) == "9.9.9.9"


def test_client_ip_unknown_without_header_or_client():
    assert client_ip(make_request(host=None)) == "unknown"


def test_uploads_with_different_forwarded_ips_limited_separately(
        tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    seller_url = create_shop(client)

    def upload_as(ip):
        return client.post(
            seller_url + "/upload",
            files={"video": ("clip.mp4", b"fakevideo", "video/mp4")},
            headers={"x-forwarded-for": ip})

    for _ in range(5):
        assert upload_as("1.1.1.1").status_code in (302, 303)
    assert upload_as("1.1.1.1").status_code == 429
    assert upload_as("2.2.2.2").status_code in (302, 303)


# --- Judge try-it mode ---

def test_try_creates_judge_shop_with_banner(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    response = client.get("/try")
    assert response.status_code in (302, 303)
    seller_url = response.headers["location"]
    html = client.get(seller_url).text
    assert JUDGE_BANNER in html
    assert 'href="/try"' in client.get("/").text
    conn = db.connect(tmp_path / "data")
    try:
        shop = conn.execute("SELECT * FROM shops").fetchone()
        assert shop["is_judge"] == 1 and shop["listed"] == 0
        expires = datetime.fromisoformat(shop["expires_at"])
        fresh = datetime.now(UTC) + timedelta(days=7)
        assert timedelta(0) < fresh - expires < timedelta(hours=1)
    finally:
        conn.close()


def test_try_shop_never_appears_in_market(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    token = client.get("/try").headers["location"].rsplit("/e/", 1)[1]
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        version_id = db.approve(conn, session_id, [clean_draft()])
        db.set_published(conn, version_id, True)
        listings = find_listings(
            conn, Query([Want("tomato", None, None, None)], None, None),
            datetime.now(UTC))
    finally:
        conn.close()
    assert listings == []


# --- Expiry purge ---

def seed_judge_shop_with_files(conn, data_dir, expired=True):
    shop_id, slug, _ = db.create_shop(
        conn, name="Judge Test", phone="+910000000000", area="Trial",
        language="en", currency="INR", shop_type="vegetable",
        is_judge=True, listed=False)
    when = datetime.now(UTC) + timedelta(days=-1 if expired else 6)
    conn.execute("UPDATE shops SET expires_at = ? WHERE id = ?",
                 (when.isoformat(), shop_id))
    conn.commit()
    session_id = db.create_session(conn, shop_id, "video")
    session_dir = data_dir / "sessions" / str(session_id)
    (session_dir / "frames").mkdir(parents=True, exist_ok=True)
    frame = session_dir / "frames" / "f_0.jpg"
    frame.write_bytes(b"fakeframe")
    uploads = data_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    upload = uploads / f"{session_id}_clip.mp4"
    upload.write_bytes(b"fakevideo")
    photos = data_dir / "photos"
    photos.mkdir(parents=True, exist_ok=True)
    photo = photos / f"s{session_id}_0.jpg"
    photo.write_bytes(b"fakephoto")
    item = clean_draft()
    item.photo = str(photo)
    db.save_drafts(conn, session_id, [item])
    return slug, [session_dir, upload, photo]


def test_purge_removes_expired_judge_shop_files_and_slug_404s(
        tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    conn = db.connect(data_dir)
    try:
        slug, paths = seed_judge_shop_with_files(conn, data_dir, expired=True)
        removed = db.purge_expired(conn, data_dir, datetime.now(UTC))
        assert removed == 1
        assert db.shop_by_slug(conn, slug) is None
    finally:
        conn.close()
    assert all(not path.exists() for path in paths)
    client = make_client(tmp_path, monkeypatch)
    assert client.get(f"/s/{slug}").status_code == 404


def test_purge_keeps_unexpired_judge_shop(tmp_path):
    data_dir = tmp_path / "data"
    conn = db.connect(data_dir)
    try:
        slug, _ = seed_judge_shop_with_files(conn, data_dir, expired=False)
        assert db.purge_expired(conn, data_dir, datetime.now(UTC)) == 0
        assert db.shop_by_slug(conn, slug) is not None
    finally:
        conn.close()


def seed_media_shop(conn, data_dir, name, is_demo):
    shop_id, _, _ = db.create_shop(
        conn, name=name, phone="+914400000000", area="Koyambedu",
        language="ta", currency="INR", shop_type="vegetable",
        is_demo=is_demo, listed=is_demo)
    session_id = db.create_session(conn, shop_id, "video")
    photo = data_dir / "photos" / f"s{session_id}_0.jpg"
    photo.parent.mkdir(parents=True, exist_ok=True)
    photo.write_bytes(b"fakephoto")
    session_dir = data_dir / "sessions" / str(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    clip = session_dir / "audio.wav"
    clip.write_bytes(b"fakeaudio")
    return session_id, photo, session_dir


def test_purge_old_non_demo_media_keeps_demo_and_fresh(tmp_path):
    data_dir = tmp_path / "data"
    conn = db.connect(data_dir)
    try:
        old_id, old_photo, old_dir = seed_media_shop(conn, data_dir, "Old", False)
        _, demo_photo, demo_dir = seed_media_shop(conn, data_dir, "Demo", True)
        _, fresh_photo, _ = seed_media_shop(conn, data_dir, "Fresh", False)
        for path in (old_photo, old_dir / "audio.wav", demo_photo,
                     demo_dir / "audio.wav"):
            backdate(path, 31)
        assert db.purge_expired(conn, data_dir, datetime.now(UTC)) == 0
    finally:
        conn.close()
    assert not old_photo.exists()
    assert not old_dir.exists()
    assert demo_photo.exists() and demo_dir.exists()
    assert fresh_photo.exists()
    assert old_id is not None


def test_purge_runs_at_startup_and_before_upload(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    conn = db.connect(data_dir)
    try:
        slug, _ = seed_judge_shop_with_files(conn, data_dir, expired=True)
    finally:
        conn.close()
    make_client(tmp_path, monkeypatch)  # startup purge
    conn = db.connect(data_dir)
    try:
        assert db.shop_by_slug(conn, slug) is None
        slug2, _ = seed_judge_shop_with_files(conn, data_dir, expired=True)
    finally:
        conn.close()
    client = TestClient(create_app(make_settings(tmp_path)),
                        follow_redirects=False)

    def fake_submit(fn, *args):
        fn(*args)

    def fake_process(conn, session_id, video, *, settings, ledger):
        db.save_drafts(conn, session_id, [clean_draft()])
        db.set_session_status(conn, session_id, "review", "ok")

    monkeypatch.setattr("app.web.seller.jobs.submit", fake_submit)
    monkeypatch.setattr("app.web.seller.process_video_session", fake_process)
    seller_url = create_shop(client)
    assert post_upload(client, seller_url).status_code in (302, 303)
    conn = db.connect(data_dir)
    try:
        assert db.shop_by_slug(conn, slug2) is None
    finally:
        conn.close()


# --- Demo budget ---

def test_upload_over_budget_shows_budget_page(tmp_path, monkeypatch):
    settings = make_settings(tmp_path, DAILY_BUDGET_USD="0")
    client = make_client(tmp_path, monkeypatch, settings=settings)
    seller_url = create_shop(client)
    response = post_upload(client, seller_url)
    assert BUDGET_MSG in response.text
    conn = db.connect(tmp_path / "data")
    try:
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    finally:
        conn.close()


def test_processing_cost_cap_shows_budget_message(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = db.create_shop(
            conn, name="Shop", phone="1", area="A", language="ta",
            currency="INR", shop_type="vegetable")
        session_id = db.create_session(conn, shop_id, "video")

        def raising_length(video, max_s):
            raise CostCapExceeded("daily Meta budget reached")

        monkeypatch.setattr("app.pipeline.run.check_length", raising_length)
        ledger = CostLedger(tmp_path / "costs.db", 100.0)
        process_video_session(conn, session_id, tmp_path / "clip.mp4",
                              settings=settings, ledger=ledger)
        row = conn.execute("SELECT status, message FROM sessions WHERE id = ?",
                           (session_id,)).fetchone()
    finally:
        conn.close()
    assert row["status"] == "failed"
    assert row["message"] == BUDGET_MSG


# --- Demo seeding ---

def run_seed(monkeypatch, tmp_path, items, name="Demo Stall"):
    out_path = write_run_json(tmp_path / "eval" / "out" / "clip1.json", items)
    data_dir = tmp_path / "seeddata"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("MODEL_API_KEY", "k")
    monkeypatch.chdir(tmp_path)
    code = seed_demo.main(
        [str(out_path), "--name", name, "--area", "Koyambedu"])
    return code, data_dir


def test_seed_demo_creates_listed_published_demo_shop(tmp_path, monkeypatch):
    items = [draft_dict("tomato", "தக்காளி", 18),
             draft_dict("onion", "வெங்காயம்", 25)]
    code, data_dir = run_seed(monkeypatch, tmp_path, items)
    assert code == 0
    conn = db.connect(data_dir)
    try:
        shop = conn.execute("SELECT * FROM shops").fetchone()
        assert shop["is_demo"] == 1 and shop["listed"] == 1
        assert shop["name"] == "Demo Stall" and shop["area"] == "Koyambedu"
        version_id = db.latest_version(conn, shop["id"], published_only=True)
        assert version_id is not None
        slug = shop["slug"]
    finally:
        conn.close()
    client = TestClient(
        create_app(make_settings(tmp_path, DATA_DIR=str(data_dir))))
    html = client.get(f"/s/{slug}").text
    from app.web.i18n import t_for
    assert t_for("en")("hp.demo") in html
    assert "₹18" in html and "₹25" in html


def test_seed_demo_refuses_blocking_flags(tmp_path, monkeypatch, capsys):
    flagged = draft_dict("tomato", "தக்காளி", 18, flags=[
        Flag(field="price", code="SOUND_ALIKE",
             message="did you say 18 or 80?", options=["18", "80"])])
    code, data_dir = run_seed(monkeypatch, tmp_path, [flagged])
    assert code != 0
    captured = capsys.readouterr()
    assert "SOUND_ALIKE" in captured.out + captured.err
    assert "tomato" in captured.out + captured.err
    conn = db.connect(data_dir)
    try:
        assert conn.execute("SELECT COUNT(*) FROM shops").fetchone()[0] == 0
    finally:
        conn.close()
