"""Task 30: synthetic language clips + benchmark harness (no network, no `say`)."""

import json
from pathlib import Path

SAMPLE_SAY = """\
Aman                en_IN    # Hello! My name is Aman.
Vani (Tamil (India)) ta_IN    # Hello! My name is Vani.
Lekha (Hindi (India)) hi_IN    # नमस्ते, मेरा नाम लेखा है।
Eddy (French (France)) fr_FR    # Bonjour, je m'appelle Eddy.
Thomas (French (France)) fr_FR    # Bonjour, je m'appelle Thomas.
Rishi (English (India)) en_IN    # Hello! My name is Rishi.
Majed (Arabic (World)) ar_001   # مرحبًا! اسمي ماجد.
"""


def test_select_voice_first_match():
    from scripts.make_lang_clips import select_voice

    assert select_voice(SAMPLE_SAY, "en_IN") == "Aman"
    assert select_voice(SAMPLE_SAY, "ta_IN") == "Vani (Tamil (India))"
    assert select_voice(SAMPLE_SAY, "fr_FR") == "Eddy (French (France))"
    assert select_voice(SAMPLE_SAY, "ar_001") == "Majed (Arabic (World))"


def test_select_voice_missing_returns_none():
    from scripts.make_lang_clips import select_voice

    assert select_voice(SAMPLE_SAY, "mr_IN") is None
    assert select_voice(SAMPLE_SAY, "fil_PH") is None
    assert select_voice("", "en_IN") is None


def test_split_sentences_english_and_danda_and_cjk():
    from scripts.make_lang_clips import split_sentences

    en = "Tomato, one kilo, 40 rupees. Onion, one kilo, 30 rupees. Banana, one dozen, 60 rupees. Coconut, one piece, 25 rupees."
    assert len(split_sentences(en)) == 4
    hi = "टमाटर एक किलो 40 रुपये। प्याज़ एक किलो 30 रुपये। केला एक दर्जन 60 रुपये। नारियल एक पीस 25 रुपये।"
    assert len(split_sentences(hi)) == 4
    zh = "西红柿，一公斤，8块钱。洋葱，一公斤，5块钱。香蕉，一打，12块钱。椰子，一个，10块钱。"
    parts = split_sentences(zh)
    assert len(parts) == 4
    assert all(parts)


def test_split_sentences_thai_without_punctuation_gives_four():
    from scripts.make_lang_clips import split_sentences

    th = "มะเขือเทศ หนึ่งกิโล 40 บาท หัวหอม หนึ่งกิโล 30 บาท กล้วย หนึ่งโหล 50 บาท มะพร้าว ลูกละ 25 บาท"
    parts = split_sentences(th)
    assert len(parts) == 4
    assert all(parts)
    # Every word must appear in exactly one segment, in order.
    assert " ".join(parts).split() == th.split()


def test_all_scripts_split_into_four():
    from scripts.make_lang_clips import split_sentences

    data = json.loads(Path("eval/lang/scripts.json").read_text())
    assert len(data["languages"]) == 25
    for code, entry in data["languages"].items():
        parts = split_sentences(entry["text"])
        assert len(parts) == 4, code
        assert all(p.strip() for p in parts), code


def test_say_cmd_shape():
    from scripts.make_lang_clips import build_say_cmd

    cmd = build_say_cmd("Vani (Tamil (India))", "வணக்கம்", Path("/tmp/p.aiff"))
    assert cmd[0:4] == ["say", "-v", "Vani (Tamil (India))", "-o"]
    assert str(Path("/tmp/p.aiff")) in cmd
    assert "வணக்கம்" in cmd


def test_segment_ffmpeg_cmd_portrait_white():
    from scripts.make_lang_clips import build_concat_cmd, build_segment_cmd

    seg = build_segment_cmd(Path("photo.jpg"), Path("part.aiff"), Path("seg0.mp4"))
    blob = " ".join(seg)
    assert seg[0] == "ffmpeg"
    assert "photo.jpg" in seg and "part.aiff" in seg and "seg0.mp4" in seg
    assert "720" in blob and "1280" in blob
    assert "white" in blob
    assert "scale" in blob and "pad" in blob
    assert "-shortest" in seg

    concat = build_concat_cmd(Path("list.txt"), Path("out.mp4"))
    assert concat[0] == "ffmpeg"
    assert "-f" in concat and "concat" in concat
    assert "list.txt" in concat and "out.mp4" in concat


def test_answers_format_matches_eval_answers():
    from scripts.make_lang_clips import answers_for

    data = json.loads(Path("eval/lang/scripts.json").read_text())
    entry = data["languages"]["ta"]
    answers = answers_for("ta", entry)
    assert answers["clip"] == "ta.mp4"
    assert len(answers["items"]) == 4
    key_sample = json.loads(Path("eval/answers/synth1.json").read_text())
    sample_keys = set(key_sample["items"][0].keys())
    for item, want in zip(answers["items"], entry["answers"]):
        for field in ("name_en", "price", "per_amount", "unit"):
            assert field in item
        assert {"name_en", "price", "per_amount", "unit"} <= sample_keys
        assert item["name_en"] == want["name_en"]
        assert item["price"] == want["price"]
        assert item["per_amount"] == want["per_amount"]
        assert item["unit"] == want["unit"]
        assert item["variety"] is None
        assert "expect_flags" in item


def test_score_lang_uses_existing_scoring():
    from scripts.lang_benchmark import score_lang

    key = {
        "clip": "ta.mp4",
        "items": [
            {"name_en": "tomato", "price": 40, "per_amount": 1, "unit": "kg", "expect_flags": []},
            {"name_en": "onion", "price": 30, "per_amount": 1, "unit": "kg", "expect_flags": []},
            {"name_en": "banana", "price": 60, "per_amount": 1, "unit": "dozen", "expect_flags": []},
            {"name_en": "coconut", "price": 25, "per_amount": 1, "unit": "piece", "expect_flags": []},
        ],
    }
    out = {
        "clip": "ta.mp4",
        "items": [
            {
                "name_en": "tomato",
                "price_lines": [{"price": "40", "per_amount": "1", "unit": "kg"}],
                "flags": [],
            },
            {
                "name_en": "onion",
                "price_lines": [{"price": "99", "per_amount": "1", "unit": "kg"}],
                "flags": [{"code": "NUMBER_CHECK", "blocking": True}],
            },
            {
                "name_en": "banana",
                "price_lines": [{"price": "61", "per_amount": "1", "unit": "dozen"}],
                "flags": [],
            },
        ],
    }
    row = score_lang(key, out)
    assert row["in_key"] == 4
    assert row["found"] == 3
    assert row["exact"] == 1
    assert row["flagged"] == 1
    assert row["wrong_unflagged"] == 1
    assert row["missed"] == 1


def test_markdown_table_not_tested_and_needs_work():
    from scripts.lang_benchmark import render_languages_md

    results = [
        {
            "code": "ta",
            "api_name": "Tamil",
            "native_name": "தமிழ்",
            "voice": "Vani (Tamil (India))",
            "status": "tested",
            "found": 4,
            "exact": 4,
            "flagged": 0,
            "wrong_unflagged": 0,
            "cost_usd": 0.05,
            "seconds": 12.0,
        },
        {
            "code": "fr",
            "api_name": "French",
            "native_name": "Français",
            "voice": "Eddy (French (France))",
            "status": "tested",
            "found": 4,
            "exact": 2,
            "flagged": 1,
            "wrong_unflagged": 1,
            "cost_usd": 0.06,
            "seconds": 14.0,
        },
        {
            "code": "mr",
            "api_name": "Marathi",
            "native_name": "मराठी",
            "voice": None,
            "status": "not_tested",
            "found": 0,
            "exact": 0,
            "flagged": 0,
            "wrong_unflagged": 0,
            "cost_usd": 0.0,
            "seconds": 0.0,
        },
    ]
    md = render_languages_md(results, provider="meta")
    low = md.lower()
    assert "synthetic" in low and "macos" in low
    assert "wikimedia" in low
    assert "4 items" in md
    assert "one run per language" in low
    assert "results vary" in low
    for header in (
        "native",
        "english",
        "voice",
        "found",
        "exact",
        "flagged",
        "wrong-unflagged",
        "cost",
        "seconds",
        "notes",
    ):
        assert header in low, header
    assert "not tested (no test voice)" in md
    fr_line = next(line for line in md.splitlines() if "Français" in line)
    assert "needs work" in fr_line
    mr_line = next(line for line in md.splitlines() if "မရာဎီီ" in line or "मराठी" in line)
    assert "not tested (no test voice)" in mr_line
    assert "works" not in mr_line.lower()
    assert "works" not in fr_line.lower()
