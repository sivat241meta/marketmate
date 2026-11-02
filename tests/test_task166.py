"""Task 166: the database stays safe under concurrent use.

- connect() runs schema/migrations once per process per path, so a page
  view never writes; busy_timeout is 30 s.
- Pipeline writes retry on "database is locked" (~60 s); progress-only
  writes are logged and skipped instead of failing the session.
- storage.commit() is throttled to one real commit per 3 s window.
"""

import json
import sqlite3
import sys
import threading
import time
from types import SimpleNamespace

from app import db, storage
from app.costs import CostLedger
from app.pipeline import run as run_mod
from tests.test_db import make_draft, make_shop


def _hold_exclusive_lock(tmp_path, session_id, ready, release=None,
                         hold_s=0.0):
    """Writer thread body: hold an EXCLUSIVE lock, then release it."""
    conn = db.connect(tmp_path)
    try:
        conn.execute("BEGIN EXCLUSIVE")
        conn.execute("UPDATE sessions SET message = 'held' WHERE id = ?",
                     (session_id,))
        ready.set()
        if release is not None:
            assert release.wait(timeout=30)
        elif hold_s:
            time.sleep(hold_s)
        conn.commit()
    finally:
        conn.close()


def test_second_connect_writes_nothing(tmp_path):
    first = db.connect(tmp_path)
    try:
        shop_id, _, _ = make_shop(first)
        session_id = db.create_session(first, shop_id, "video")
        item = make_draft()
        item.confirmed = True
        db.approve(first, session_id, [item])
        # A row the old per-connect migration would rewrite.
        first.execute("UPDATE items SET match_key = NULL")
        first.commit()
    finally:
        first.close()
    second = db.connect(tmp_path)
    try:
        assert second.total_changes == 0
        assert second.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
        assert second.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1
    finally:
        second.close()


def test_pipeline_writes_retry_through_lock(tmp_path):
    conn = db.connect(tmp_path)
    shop_id, _, _ = make_shop(conn)
    session_id = db.create_session(conn, shop_id, "video")
    db.set_session_status(conn, session_id, "processing", "start")
    # Fail fast so the retry layer (not just busy_timeout) does the waiting.
    conn.execute("PRAGMA busy_timeout = 30")
    ready = threading.Event()
    holder = threading.Thread(target=_hold_exclusive_lock,
                              args=(tmp_path, session_id, ready, None, 2.0))
    holder.start()
    assert ready.wait(timeout=10)
    try:
        db.note_stage(conn, session_id, "photos", detail="item 9 of 17")
        db.note_status(conn, session_id, "Picking a photo for each item")
        db.save_drafts(conn, session_id, [make_draft()])
    finally:
        holder.join(timeout=30)
        conn.close()
    assert not holder.is_alive()
    check = db.connect(tmp_path)
    try:
        row = check.execute("SELECT stage, stage_detail, status FROM sessions"
                            " WHERE id = ?", (session_id,)).fetchone()
        assert (row["stage"], row["stage_detail"]) == ("photos", "item 9 of 17")
        assert row["status"] == "processing"
        assert len(db.load_drafts(check, session_id)) == 1
    finally:
        check.close()


def test_session_not_failed_under_6s_lock(tmp_path, monkeypatch):
    """The live incident: progress writes during a 6 s lock must succeed."""
    conn = db.connect(tmp_path)
    shop_id, _, _ = make_shop(conn)
    session_id = db.create_session(conn, shop_id, "video")
    db.set_session_status(conn, session_id, "failed", "old failure")
    session_dir = tmp_path / "sessions" / str(session_id)
    session_dir.mkdir(parents=True)
    (session_dir / "transcript.json").write_text(json.dumps({
        "text": "tomato kilo twenty", "duration_ms": 1000,
        "turns": [{"id": 1, "start_ms": 0, "end_ms": 1000,
                   "text": "tomato kilo twenty"}]}))
    monkeypatch.setattr(run_mod, "extract_items", lambda *a, **k: [])
    settings = SimpleNamespace(data_dir=str(tmp_path))
    ledger = CostLedger(tmp_path / "costs.db", 1.0)
    ready = threading.Event()
    holder = threading.Thread(target=_hold_exclusive_lock,
                              args=(tmp_path, session_id, ready, None, 6.0))
    holder.start()
    assert ready.wait(timeout=10)
    try:
        run_mod.reprocess(conn, session_id, settings=settings, ledger=ledger)
    finally:
        holder.join(timeout=60)
        conn.close()
    assert not holder.is_alive()
    check = db.connect(tmp_path)
    try:
        row = check.execute("SELECT status FROM sessions WHERE id = ?",
                            (session_id,)).fetchone()
        assert row["status"] == "review"
    finally:
        check.close()


def test_progress_only_writes_never_fail_session(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "LOCK_RETRY_SECONDS", 0.2)
    conn = db.connect(tmp_path)
    shop_id, _, _ = make_shop(conn)
    session_id = db.create_session(conn, shop_id, "video")
    db.set_session_status(conn, session_id, "processing", "working")
    conn.execute("PRAGMA busy_timeout = 10")
    ready = threading.Event()
    release = threading.Event()
    holder = threading.Thread(target=_hold_exclusive_lock,
                              args=(tmp_path, session_id, ready, release, 0.0))
    holder.start()
    assert ready.wait(timeout=10)
    try:
        # Progress-only writes give up quietly under a stuck lock.
        db.note_stage(conn, session_id, "photos", detail="item 9 of 17")
        db.note_status(conn, session_id, "still working")
        db.fail_session(conn, session_id, "boom")
        # Essential writes still raise after their retries...
        with_fail = False
        try:
            db.set_session_status(conn, session_id, "review", "done")
        except sqlite3.OperationalError as exc:
            with_fail = db.is_locked_error(exc)
        assert with_fail
        # ...but a lock error is never recorded as a session failure.
        db.report_pipeline_error(conn, session_id,
                                 sqlite3.OperationalError("database is locked"),
                                 "whatever")
    finally:
        release.set()
        holder.join(timeout=30)
        conn.close()
    assert not holder.is_alive()
    check = db.connect(tmp_path)
    try:
        row = check.execute("SELECT status FROM sessions WHERE id = ?",
                            (session_id,)).fetchone()
        assert row["status"] == "processing"
        # A real pipeline error still fails the session.
        db.report_pipeline_error(check, session_id, ValueError("real"),
                                 "Something went wrong")
        row = check.execute("SELECT status FROM sessions WHERE id = ?",
                            (session_id,)).fetchone()
        assert row["status"] == "failed"
    finally:
        check.close()


class _FakeVolume:
    def __init__(self, calls):
        self._calls = calls

    def commit(self):
        self._calls.append("commit")


class _FakeModal:
    def __init__(self, calls):
        self._calls = calls

    @property
    def Volume(self):
        calls = self._calls

        class _Volumes:
            @staticmethod
            def from_name(name):
                assert name == "marketmate-data"
                return _FakeVolume(calls)

        return _Volumes()


def _modal_env(monkeypatch, calls):
    storage.reset_throttle_for_tests()
    monkeypatch.setenv("MARKETMATE_ON_MODAL", "1")
    monkeypatch.setattr(storage, "COMMIT_MIN_INTERVAL_S", 0.3)
    monkeypatch.setitem(sys.modules, "modal", _FakeModal(calls))


def test_commit_throttle_coalesces_many_calls(monkeypatch):
    assert storage.COMMIT_MIN_INTERVAL_S == 3.0
    calls = []
    _modal_env(monkeypatch, calls)
    try:
        for _ in range(20):
            storage.commit()
        assert calls == ["commit"]
        deadline = time.time() + 10
        while len(calls) < 2 and time.time() < deadline:
            time.sleep(0.05)
        assert calls == ["commit", "commit"]
    finally:
        storage.reset_throttle_for_tests()


def test_commit_now_is_immediate_and_cancels_pending(monkeypatch):
    calls = []
    _modal_env(monkeypatch, calls)
    try:
        storage.commit()
        storage.commit()  # throttled: schedules the trailing timer
        storage.commit_now()  # a finished session commits at once
        assert calls == ["commit", "commit"]
        time.sleep(0.6)
        assert calls == ["commit", "commit"]
    finally:
        storage.reset_throttle_for_tests()
