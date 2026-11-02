"""Task 19: Modal volume commits (storage.commit, middleware, jobs)."""

import sys
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app import jobs, storage
from app.config import load_settings
from app.web.main import create_app


@pytest.fixture(autouse=True)
def _fresh_throttle():
    storage.reset_throttle_for_tests()
    yield
    storage.reset_throttle_for_tests()


class _ExplodingModal:
    def __getattr__(self, name):
        raise AssertionError(f"modal must not be touched locally (got {name})")


class _FakeVolume:
    def __init__(self, calls):
        self._calls = calls

    def commit(self):
        self._calls.append("commit")


class _FakeVolumes:
    def __init__(self, calls, names):
        self._calls = calls
        self._names = names

    def from_name(self, name):
        self._names.append(name)
        return _FakeVolume(self._calls)


class _FakeModal:
    def __init__(self, calls, names):
        self.Volume = _FakeVolumes(calls, names)


def test_commit_is_noop_without_env_var(monkeypatch):
    monkeypatch.delenv("MARKETMATE_ON_MODAL", raising=False)
    monkeypatch.setitem(sys.modules, "modal", _ExplodingModal())
    assert storage.commit() is None


def test_commit_calls_volume_commit_on_modal(monkeypatch):
    monkeypatch.setenv("MARKETMATE_ON_MODAL", "1")
    calls, names = [], []
    monkeypatch.setitem(sys.modules, "modal", _FakeModal(calls, names))
    assert storage.commit() is None
    assert names == ["marketmate-data"]
    assert calls == ["commit"]
    assert storage.VOLUME_NAME == "marketmate-data"


def test_commit_failure_does_not_raise(monkeypatch, caplog):
    class _FailingVolume:
        def commit(self):
            raise RuntimeError("volume unavailable")

    class _FailingVolumes:
        def from_name(self, name):
            return _FailingVolume()

    class _FailingModal:
        Volume = _FailingVolumes()

    monkeypatch.setenv("MARKETMATE_ON_MODAL", "1")
    monkeypatch.setitem(sys.modules, "modal", _FailingModal())
    assert storage.commit() is None  # must not raise
    assert "volume commit failed" in caplog.text


def make_client(tmp_path):
    settings = load_settings({"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")})
    return TestClient(create_app(settings), follow_redirects=False)


SHOP_FORM = {
    "name": "Kannan Store",
    "phone": "+914400000000",
    "area": "Koyambedu",
    "language": "ta",
    "currency": "INR",
    "type": "vegetable",
}


def test_post_triggers_commit_once(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(storage, "commit", lambda: calls.append(1))
    client = make_client(tmp_path)
    response = client.post("/new", data=SHOP_FORM)
    assert response.status_code in (302, 303)
    assert len(calls) == 1


def test_get_does_not_trigger_commit(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(storage, "commit", lambda: calls.append(1))
    client = make_client(tmp_path)
    assert client.get("/").status_code == 200
    assert calls == []


def _wait_for(calls, count=1, timeout=10.0):
    deadline = time.time() + timeout
    while len(calls) < count and time.time() < deadline:
        time.sleep(0.01)
    assert len(calls) == count


def test_finished_job_calls_commit(monkeypatch):
    calls = []
    monkeypatch.setattr(storage, "commit_now", lambda: calls.append(1))
    done = threading.Event()
    jobs.submit(done.set)
    assert done.wait(timeout=10)
    _wait_for(calls)


def test_failed_job_still_calls_commit(monkeypatch):
    calls = []
    monkeypatch.setattr(storage, "commit_now", lambda: calls.append(1))
    done = threading.Event()

    def boom():
        done.set()
        raise RuntimeError("job blew up")

    jobs.submit(boom)
    assert done.wait(timeout=10)
    _wait_for(calls)
