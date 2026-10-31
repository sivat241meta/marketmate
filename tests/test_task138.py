"""Task 138: upload bubble waits up to 8 min, no mid-word hyphens, voice card.

1. composer.js polls for up to 8 minutes (back-off 2 s -> 5 s), shows the
   status JSON's active-step label while waiting, and renders only the
   current step plus finished ones — never "Done" before done.
2. Headings and composer text use `hyphens: manual` so English and Tamil
   words are never split with a hyphen on phones.
3. The homepage voice card (<button class="svc">) lays out from the top
   like the anchor cards (Task 133's appearance:none was not enough:
   browsers vertically centre button content).
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSER_JS = ROOT / "app" / "web" / "static" / "composer.js"
APP = (ROOT / "app" / "web" / "static" / "app.css").read_text()
V13 = (ROOT / "app" / "web" / "static" / "css" / "v13.css").read_text()
COMPOSER_CSS = (ROOT / "app" / "web" / "static" / "css"
                / "composer.css").read_text()
HOME = (ROOT / "app" / "web" / "templates" / "home.html").read_text()


def _block(css: str, selector: str) -> str:
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, selector
    return m.group(1)


# --- 1. eight-minute poll with real step labels --------------------------------


def test_composer_poll138_node_tests():
    node = shutil.which("node")
    assert node, "node is required"
    result = subprocess.run([node, "tests/js/composer_poll138.test.mjs"],
                            cwd=ROOT, check=False, capture_output=True,
                            text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_poll_limit_is_eight_minutes():
    source = COMPOSER_JS.read_text()
    m = re.search(r"var POLL_BUDGET_MS = ([^;]+);", source)
    assert m, "POLL_BUDGET_MS constant"
    budget = eval(m.group(1), {"__builtins__": {}})  # arithmetic only
    assert budget >= 8 * 60 * 1000
    poll = source.split("function pollStatus")[1].split("function postForm")[0]
    assert "pollElapsedMs(count) >= POLL_BUDGET_MS" in poll
    assert "showOpenLink(ctx, bubble, finalUrl)" in poll
    assert "pollDelay(count)" in poll
    assert "POLL_MAX" not in source  # the 60 s give-up is gone


def test_step_label_comes_from_active_step():
    source = COMPOSER_JS.read_text()
    assert '"active"' in source.split("function activeStepLabel")[1].split(
        "function bubbleSteps")[0]
    poll = source.split("function pollStatus")[1].split("function postForm")[0]
    assert "activeStepLabel(data)" in poll
    assert "setActiveLabel(bubble, label)" in poll
    assert "activeStepLabel" in source.split("initComposer.testHooks")[1]


def test_no_done_label_before_done():
    source = COMPOSER_JS.read_text()
    add = source.split("function addStatusBubble")[1].split(
        "function setStep")[0]
    assert "setStep(bubble, 0)" in add  # first render: sending only
    assert "bubbleSteps" in source.split("initComposer.testHooks")[1]
    setter = source.split("function setStep")[1].split(
        "function replaceBubble")[0]
    assert "bubbleSteps(active, labels)" in setter
    opener = source.split("function showOpenLink")[1].split(
        "function langOptions")[0]
    assert "ctx.str.done" not in opener
    assert "stillWorking" in opener


# --- 2. no mid-word hyphens ------------------------------------------------------


def test_headings_use_manual_hyphens():
    base = _block(APP, "h1, h2, h3")
    assert "hyphens: manual" in base
    card = _block(APP, ".card h1, .card h2")
    assert "hyphens: manual" in card
    assert "hyphens: auto" not in card
    v13 = _block(V13, "body.v13 h1,body.v13 h2,body.v13 h3,body.v13 .svc-t")
    assert "hyphens:manual" in v13.replace(" ", "")
    bubble = _block(COMPOSER_CSS, ".composer-bubble")
    assert "hyphens: manual" in bubble
    hint = _block(COMPOSER_CSS, ".composer-hint")
    assert "hyphens: manual" in hint


# --- 3. voice card aligned --------------------------------------------------------


def test_voice_button_starts_at_top():
    btn = _block(V13, "body.v13 button.svc")
    flat = btn.replace(" ", "")
    assert "display:flex" in flat
    assert "flex-direction:column" in flat
    assert "align-items:flex-start" in flat
    assert "justify-content:flex-start" in flat
    # The voice hooks survive on the button.
    m = re.search(r'<button[^>]*class="svc"[^>]*>', HOME)
    assert m
    assert "data-search-open" in m.group(0)
    assert "data-search-voice" in m.group(0)
