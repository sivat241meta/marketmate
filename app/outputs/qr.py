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
    """QR code rendered server-side as an inline SVG string."""
    import qrcode.image.svg

    image = qrcode.make(payload, image_factory=qrcode.image.svg.SvgImage)
    buf = io.BytesIO()
    image.save(buf)
    return buf.getvalue().decode("utf-8")
