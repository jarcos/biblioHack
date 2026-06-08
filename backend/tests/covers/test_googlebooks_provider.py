"""Unit test for the Google Books thumbnail-URL parser (pure, no network)."""

from __future__ import annotations

from bibliohack.covers.infrastructure.providers.googlebooks import thumbnail_url


def test_prefers_thumbnail_forces_https_and_drops_curl() -> None:
    payload = {
        "items": [
            {
                "volumeInfo": {
                    "imageLinks": {
                        "smallThumbnail": "http://books.google.com/s?zoom=5&edge=curl",
                        "thumbnail": "http://books.google.com/t?zoom=1&edge=curl",
                    }
                }
            }
        ]
    }
    assert thumbnail_url(payload) == "https://books.google.com/t?zoom=1"


def test_falls_back_to_small_thumbnail() -> None:
    payload = {"items": [{"volumeInfo": {"imageLinks": {"smallThumbnail": "http://g/s"}}}]}
    assert thumbnail_url(payload) == "https://g/s"


def test_none_when_no_usable_image() -> None:
    assert thumbnail_url({"items": []}) is None
    assert thumbnail_url({"items": [{"volumeInfo": {}}]}) is None
    assert thumbnail_url({"totalItems": 0}) is None
    assert thumbnail_url("not-a-dict") is None
