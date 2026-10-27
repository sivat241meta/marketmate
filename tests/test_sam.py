import json
from pathlib import Path

import pytest
from httpx import Response

from app.config import load_settings
from app.costs import CostLedger
from app.meta.sam import SAM_USD_PER_IMAGE, find_boxes, parse_sam_text
from app.models import Box

_SAM_URL = "https://api.meta.ai/v1/responses"


def test_parse_sam_boxes():
    s = ("<0f>1,<|box;x1=10;y1=20;x2=110;y2=220;w=640;h=480|>"
         "<|mask;x=0;y=0;data=2,2,~abc|>,2,"
         "<|box;x1=0;y1=0;x2=5;y2=5;w=640;h=480|><|mask;x=0;y=0;data=1,1,~a|>")
    assert parse_sam_text(s)[0] == Box(10, 20, 110, 220, 640, 480, None)
    assert len(parse_sam_text(s)) == 2


def test_sam_zero_matches():
    assert parse_sam_text("") == []


def test_parse_sam_frame_fixture():
    boxes = parse_sam_text(Path("tests/fixtures/sam_frame.txt").read_text())
    assert boxes and all(b.x2 > b.x1 and b.y2 > b.y1 for b in boxes)


def test_find_boxes_stream(respx_mock, tmp_path):
    ledger = CostLedger(tmp_path / "c.db", 100.0)
    settings = load_settings({"MODEL_API_KEY": "k"})
    sse = ('data: {"type": "response.output_text.delta", "delta": "<0f>1,<|box;x1=10;"}\n\n'
           'data: {"type": "response.output_text.delta", "delta": "y1=20;x2=110;y2=220;w=640;h=480|>"}\n\n'
           'data: {"type": "response.completed", "response": {}}\n\n')
    route = respx_mock.post(_SAM_URL).mock(return_value=Response(200, text=sse))
    image = tmp_path / "f.jpg"
    image.write_bytes(b"fakejpeg")
    assert find_boxes(image, "tomato", ledger=ledger, settings=settings) == [
        Box(10, 20, 110, 220, 640, 480, None)]
    assert route.call_count == 1
    assert ledger.today_usd("meta") == pytest.approx(SAM_USD_PER_IMAGE)
    sent = json.loads(route.calls[0].request.content)
    assert sent["stream"] is True and sent["model"] == "sam-3.1"
