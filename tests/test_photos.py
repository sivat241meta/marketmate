from PIL import Image

from app.models import Box, Frame
from app.pipeline.photos import crop_to_boxes, make_photo


def make_image(path, size=(640, 480)):
    Image.new("RGB", size, (200, 30, 30)).save(path, "JPEG")
    return path


def test_crop_union_padded(tmp_path):
    image = make_image(tmp_path / "in.jpg")
    out = tmp_path / "out.jpg"
    boxes = [Box(100, 100, 200, 200, 640, 480, None),
             Box(300, 100, 400, 200, 640, 480, None)]
    crop_to_boxes(image, boxes, out)
    assert Image.open(out).size == (316, 116)


def test_crop_uses_six_largest(tmp_path):
    image = make_image(tmp_path / "in.jpg")
    out = tmp_path / "out.jpg"
    boxes = [Box(100, 100, 200, 200, 640, 480, None),
             Box(300, 100, 400, 200, 640, 480, None),
             Box(120, 120, 130, 130, 640, 480, None),
             Box(140, 120, 150, 130, 640, 480, None),
             Box(160, 120, 170, 130, 640, 480, None),
             Box(180, 120, 190, 130, 640, 480, None),
             Box(600, 400, 605, 405, 640, 480, None)]
    crop_to_boxes(image, boxes, out)
    assert Image.open(out).size == (316, 116)


def test_crop_no_boxes_centre(tmp_path):
    image = make_image(tmp_path / "in.jpg")
    out = tmp_path / "out.jpg"
    crop_to_boxes(image, [], out)
    assert Image.open(out).size == (512, 384)


def test_make_photo_wires_find_boxes(monkeypatch, tmp_path):
    from app.config import load_settings
    from app.costs import CostLedger

    seen = {}

    def fake_find_boxes(image, noun, **kwargs):
        seen["noun"] = noun
        return [Box(100, 100, 200, 200, 640, 480, None)]

    monkeypatch.setattr("app.pipeline.photos.find_boxes", fake_find_boxes)
    frame = Frame(make_image(tmp_path / "frame.jpg"), 5000)
    out = tmp_path / "photo.jpg"
    ledger = CostLedger(tmp_path / "c.db", 100.0)
    settings = load_settings({"MODEL_API_KEY": "k"})
    assert make_photo(frame, "tomato", out, ledger=ledger, settings=settings) == out
    assert seen["noun"] == "tomato"
    assert Image.open(out).size[0] <= 800
