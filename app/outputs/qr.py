from __future__ import annotations

import io

import qrcode


def qr_png(url: str) -> bytes:
    """QR code PNG bytes pointing at the public shop page."""
    image = qrcode.make(url)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()
