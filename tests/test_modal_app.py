"""Task 19: Modal app definition (no server contact)."""

import pytest


def test_modal_app_definition():
    pytest.importorskip("modal")
    import modal_app

    assert modal_app.app.name == "marketmate"
    assert hasattr(modal_app, "web")
