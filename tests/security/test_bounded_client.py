from __future__ import annotations

import json

import httpx
import pytest

from breachgazette.clients.base import BoundedSourceClient, SourceClientError


def test_bounded_client_accepts_fixed_json_and_redirect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "/data.json"})
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=json.dumps({"ok": True}).encode(),
        )

    with BoundedSourceClient(
        allowed_origins={"https://example.gov"},
        allowed_path_prefixes=("/start", "/data.json"),
        max_response_bytes=1_000,
        rate_delay_seconds=0,
        transport=httpx.MockTransport(handler),
    ) as client:
        payload, _headers, final_url = client.get_json("https://example.gov/start")
    assert payload == {"ok": True}
    assert final_url == "https://example.gov/data.json"


@pytest.mark.parametrize(
    "url",
    [
        "http://example.gov/data",
        "https://user:secret@example.gov/data",
        "https://other.gov/data",
        "https://example.gov/unapproved",
    ],
)
def test_bounded_client_rejects_unapproved_urls(url: str) -> None:
    client = BoundedSourceClient(
        allowed_origins={"https://example.gov"},
        allowed_path_prefixes=("/data",),
        max_response_bytes=100,
        rate_delay_seconds=0,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200)),
    )
    with pytest.raises(SourceClientError):
        client.get_bytes(url, accept="text/plain")
    client.close()


def test_bounded_client_rejects_oversize_malformed_and_wrong_content_type() -> None:
    def oversized(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Length": "1000"}, content=b"x" * 1000)

    with (
        BoundedSourceClient(
            allowed_origins={"https://example.gov"},
            allowed_path_prefixes=("/data",),
            max_response_bytes=10,
            max_retries=0,
            rate_delay_seconds=0,
            transport=httpx.MockTransport(oversized),
        ) as client,
        pytest.raises(SourceClientError, match="failed safely"),
    ):
        client.get_bytes("https://example.gov/data", accept="text/plain")

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, headers={"Content-Type": "text/plain"}, content=b"{")
    )
    with BoundedSourceClient(
        allowed_origins={"https://example.gov"},
        allowed_path_prefixes=("/data",),
        max_response_bytes=100,
        max_retries=0,
        rate_delay_seconds=0,
        transport=transport,
    ) as client:
        with pytest.raises(SourceClientError, match="content type"):
            client.get_json("https://example.gov/data")
        with pytest.raises(SourceClientError, match="HTML content type"):
            client.get_text("https://example.gov/data")
