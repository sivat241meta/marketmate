from __future__ import annotations

import io

import qrcode


def qr_png(url: str) -> bytes:
    """QR code PNG bytes pointing at the public shop page."""
    image = qrcode.make(url)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def qr_svg(payload: str) -> str:
    """QR code rendered server-side as an inline SVG string.

    Uses SvgPathImage (single <path>) so inline HTML draws; SvgImage
    emits <svg:rect> which browsers ignore inline. The XML declaration
    is stripped and the <svg> keeps its viewBox; sizing comes from
    .qr-wrap svg CSS (100% width, 240px max, white background).
    """
    import qrcode.image.svg

    image = qrcode.make(payload, image_factory=qrcode.image.svg.SvgPathImage)
    buf = io.BytesIO()
    image.save(buf)
    text = buf.getvalue().decode("utf-8").strip()
    if text.startswith("<?xml"):
        _, _, text = text.partition("?>")
        text = text.strip()
    return text
