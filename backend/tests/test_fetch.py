from __future__ import annotations

import httpx
import pytest

from docmind.errors import DocumentTooLargeError, UnsafeURLError
from docmind.ingestion.fetch import ensure_public_url, fetch_url

DNS = {
    "docs.example.com": ["93.184.215.14"],
    "internal.example.com": ["10.0.0.7"],
    "metadata.example.com": ["169.254.169.254"],
    "dual.example.com": ["93.184.215.14", "127.0.0.1"],
}


async def resolver(host: str) -> list[str]:
    if host not in DNS:
        raise OSError("NXDOMAIN")
    return DNS[host]


@pytest.mark.parametrize(
    "url",
    [
        "ftp://docs.example.com/file",
        "file:///etc/passwd",
        "http://internal.example.com/",
        "http://metadata.example.com/latest/meta-data",
        "http://dual.example.com/",
        "http://user:pw@docs.example.com/",
        "http://unknown.example.com/",
        "http:///nohost",
    ],
)
async def test_unsafe_urls_rejected(url: str) -> None:
    with pytest.raises(UnsafeURLError):
        await ensure_public_url(url, resolver)


async def test_public_url_allowed() -> None:
    assert await ensure_public_url("https://docs.example.com/a?b=1", resolver)


def _transport(routes: dict[str, httpx.Response]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return routes.get(str(request.url), httpx.Response(404))

    return httpx.MockTransport(handler)


async def test_fetch_follows_safe_redirects() -> None:
    transport = _transport(
        {
            "https://docs.example.com/old": httpx.Response(301, headers={"location": "/new"}),
            "https://docs.example.com/new": httpx.Response(
                200, content=b"<p>hi</p>", headers={"content-type": "text/html"}
            ),
        }
    )
    result = await fetch_url(
        "https://docs.example.com/old",
        max_bytes=1000,
        timeout_s=5,
        resolver=resolver,
        transport=transport,
    )
    assert result.url == "https://docs.example.com/new"
    assert result.data == b"<p>hi</p>"
    assert result.content_type == "text/html"


async def test_fetch_blocks_redirect_to_private_address() -> None:
    transport = _transport(
        {
            "https://docs.example.com/go": httpx.Response(
                302, headers={"location": "http://metadata.example.com/secrets"}
            ),
        }
    )
    with pytest.raises(UnsafeURLError):
        await fetch_url(
            "https://docs.example.com/go",
            max_bytes=1000,
            timeout_s=5,
            resolver=resolver,
            transport=transport,
        )


async def test_fetch_enforces_size_limit() -> None:
    transport = _transport(
        {"https://docs.example.com/big": httpx.Response(200, content=b"x" * 5000)}
    )
    with pytest.raises(DocumentTooLargeError):
        await fetch_url(
            "https://docs.example.com/big",
            max_bytes=1000,
            timeout_s=5,
            resolver=resolver,
            transport=transport,
        )


async def test_fetch_redirect_loop() -> None:
    transport = _transport(
        {"https://docs.example.com/loop": httpx.Response(302, headers={"location": "/loop"})}
    )
    with pytest.raises(UnsafeURLError, match="redirects"):
        await fetch_url(
            "https://docs.example.com/loop",
            max_bytes=1000,
            timeout_s=5,
            resolver=resolver,
            transport=transport,
        )
