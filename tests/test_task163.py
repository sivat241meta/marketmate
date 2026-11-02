"""Task 163: judge page polish — sample first, one upload control.

Sample button + small player start step 1, a single auto-send
"Choose your video or voice note" control replaces the two upload
controls, step 2 lists the three Meta models greyed out before a run,
and the page uses the app's Inter font and colours. No model calls.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import load_settings
from app.web.i18n import STRINGS

ROOT = Path(__file__).resolve().parent.parent

NEW_KEYS = ["judge.or_own", "judge.choose", "judge.waiting"]


def _client(tmp_path, **env_extra):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    env.update(env_extra)
    client = TestClient(create_app(load_settings(env)),
                        follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    return client


def _judge_token(client):
    response = client.get("/try")
    assert response.status_code in (302, 303)
    location = response.headers["location"]
    return location.split("/e/")[1].rsplit("/judge", 1)[0]


def _sample_file(tmp_path):
    sample = tmp_path / "sample.mp4"
    sample.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0123456789" * 100)
    return sample


def _step(html, step_id, next_id):
    chunk = html.split(f'id="{step_id}"', 1)[1]
    return chunk.split(f'id="{next_id}"', 1)[0]


# --- 1. sample first ---


def test_sample_button_before_upload_control(tmp_path):
    sample = _sample_file(tmp_path)
    client = _client(tmp_path, JUDGE_SAMPLE_VIDEO=str(sample))
    token = _judge_token(client)
    html = client.get(f"/e/{token}/judge").text
    step1 = _step(html, "judge-step1", "judge-step2")
    assert "Use a real sample: VPS stall, Tamil, 64 s" in step1
    sample_pos = step1.index("data-sample-btn")
    upload_pos = step1.index('id="judge-clip"')
    assert sample_pos < upload_pos
    divider_pos = step1.index("or use your own")
    assert sample_pos < divider_pos < upload_pos


def test_small_player_not_autoplay(tmp_path):
    sample = _sample_file(tmp_path)
    client = _client(tmp_path, JUDGE_SAMPLE_VIDEO=str(sample))
    token = _judge_token(client)
    html = client.get(f"/e/{token}/judge").text
    step1 = _step(html, "judge-step1", "judge-step2")
    assert "judge-sample-video" in step1
    assert "autoplay" not in step1.lower()
    assert 'preload="metadata"' in step1
    assert "playsinline" in step1
    css = (ROOT / "app" / "web" / "static" / "css" / "judge.css").read_text()
    assert "aspect-ratio: 16 / 9" in css
    assert "max-width: 360px" in css


# --- 2. one upload control ---


def test_exactly_one_file_input_in_step1(tmp_path):
    sample = _sample_file(tmp_path)
    client = _client(tmp_path, JUDGE_SAMPLE_VIDEO=str(sample))
    token = _judge_token(client)
    html = client.get(f"/e/{token}/judge").text
    step1 = _step(html, "judge-step1", "judge-step2")
    assert step1.count('type="file"') == 1
    # The old second control is gone; the single choose button stays.
    assert "Upload video or voice note" not in html
    assert "Choose a video or voice note (gallery" not in html
    assert "Choose your video or voice note" in step1
    # Sends right after a file is picked, like the seller composer.
    assert "onchange" in step1 and "requestSubmit" in step1


def test_chips_above_hint_and_privacy_below(tmp_path):
    client = _client(tmp_path)
    token = _judge_token(client)
    html = client.get(f"/e/{token}/judge").text
    step1 = _step(html, "judge-step1", "judge-step2")
    chips = step1.index("judge-chips")
    choose = step1.index("Choose your video or voice note")
    hint = step1.index("Up to 3 minutes")
    privacy = step1.index("sent to Meta")
    assert chips < choose < hint < privacy


# --- 3. step 2 shows the models from the start ---


def test_model_rows_present_before_a_run(tmp_path):
    client = _client(tmp_path)
    token = _judge_token(client)
    html = client.get(f"/e/{token}/judge").text
    step2 = _step(html, "judge-step2", "judge-step3")
    for key in ("voice", "spark", "sam"):
        assert f'data-model="{key}"' in step2, key
    assert "muse-voice-transcribe-1.0" in step2
    assert "muse-spark-1.3" in step2
    assert "sam-3.1" in step2
    assert "speech → text" in step2
    assert "items, prices, checks" in step2
    assert "a photo for each item" in step2
    assert "waiting" in step2
    assert step2.count("is-todo") == 3


# --- 4. same look as the app, still light ---


def test_judge_uses_app_font_and_colours():
    css = (ROOT / "app" / "web" / "static" / "css" / "judge.css").read_text()
    assert '"Inter"' in css
    assert "PlusJakartaSans" not in css
    # Same colours as the app: every judge token value matches app.css.
    app = (ROOT / "app" / "web" / "static" / "app.css").read_text()
    for token, value in (("--ink", "#102A33"), ("--muted", "#56707A"),
                         ("--line", "#E2EAEE"), ("--bg", "#F3F8FA"),
                         ("--accent", "#0F766E"),
                         ("--accent-ink", "#115E59"),
                         ("--accent-soft", "#E6FAF6"), ("--blue", "#0369A1"),
                         ("--blue-soft", "#E8F4FD")):
        assert f"{token}: {value}" in css, token
        assert f"{token}: {value}" in app, token
    assert "min-height: 44px" in css
    assert "max-width: 100%" in css
    assert "white-space: normal" in css


def test_judge_page_has_no_navigation(tmp_path):
    client = _client(tmp_path)
    token = _judge_token(client)
    html = client.get(f"/e/{token}/judge").text
    assert "<nav" not in html
    for absent in ('class="rail"', 'class="topbar"', 'class="bnav"',
                   "popups.js", "pnav.js"):
        assert absent not in html, absent


# --- 5. i18n ---


def test_new_keys_exist_in_en_ta_hi():
    for lang in ("en", "ta", "hi"):
        for key in NEW_KEYS:
            assert STRINGS[lang].get(key), f"{lang} {key}"


def test_new_strings_render_in_ta_and_hi(tmp_path):
    for lang, divider, choose, waiting in (
            ("ta", "அல்லது உங்களுடையதைப்",
             "உங்கள் வீடியோ அல்லது குரல் குறிப்பைத்",
             "காத்திருக்கிறது"),
            ("hi", "या अपना इस्तेमाल करें",
             "अपना वीडियो या वॉइस नोट चुनें",
             "प्रतीक्षा में")):
        sample = _sample_file(tmp_path)
        client = _client(tmp_path, JUDGE_SAMPLE_VIDEO=str(sample))
        client.cookies.set("ui_lang", lang)
        token = _judge_token(client)
        html = client.get(f"/e/{token}/judge").text
        assert divider in html, lang
        assert choose in html, lang
        assert waiting in html, lang
