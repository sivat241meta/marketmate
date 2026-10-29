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
    assert Image.open(out).size == (480, 360)


def test_crop_uses_three_largest(tmp_path):
    image = make_image(tmp_path / "in.jpg")
    out = tmp_path / "out.jpg"
    boxes = [Box(100, 100, 200, 200, 640, 480, None),
             Box(300, 100, 400, 200, 640, 480, None),
             Box(500, 300, 600, 400, 640, 480, None),
             # Fourth-largest: must not stretch the union.
             Box(0, 0, 50, 50, 640, 480, None),
             Box(120, 120, 130, 130, 640, 480, None),
             Box(140, 120, 150, 130, 640, 480, None),
             Box(600, 400, 605, 405, 640, 480, None)]
    crop_to_boxes(image, boxes, out)
    assert Image.open(out).size == (536, 402)


def test_crop_no_boxes_centre(tmp_path):
    image = make_image(tmp_path / "in.jpg")
    out = tmp_path / "out.jpg"
    crop_to_boxes(image, [], out)
    assert Image.open(out).size == (480, 360)


def test_make_photo_wires_find_instances(monkeypatch, tmp_path):
    from app.config import load_settings
    from app.costs import CostLedger
    from app.meta.sam import SamInstance

    seen = {}

    def fake_find_instances(image, noun, **kwargs):
        seen["noun"] = noun
        return [SamInstance(Box(100, 100, 200, 200, 640, 480, None), None)]

    monkeypatch.setattr("app.pipeline.photos.find_instances",
                        fake_find_instances)
    monkeypatch.setattr("app.pipeline.photos.find_boxes",
                        lambda image, noun, **kwargs: [])
    frame = Frame(make_image(tmp_path / "frame.jpg"), 5000)
    out = tmp_path / "photo.jpg"
    ledger = CostLedger(tmp_path / "c.db", 100.0)
    settings = load_settings({"MODEL_API_KEY": "k"})
    assert make_photo(frame, "tomato", out, ledger=ledger, settings=settings) == out
    assert seen["noun"] == "tomato"
    assert Image.open(out).size[0] <= 800
