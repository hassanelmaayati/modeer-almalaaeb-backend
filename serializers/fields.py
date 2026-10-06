from typing import Annotated
from urllib.parse import urlsplit

from pydantic import AfterValidator


def _check_photo_url(value: str | None) -> str | None:
    # The frontend renders this as an <img src>, so only web URLs are allowed;
    # "" clears the photo like null does
    if value is None or not value.strip():
        return None
    value = value.strip()
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc or len(value) > 2048:
        raise ValueError("photo_url must be an http(s) URL")
    return value


PhotoUrl = Annotated[str | None, AfterValidator(_check_photo_url)]
