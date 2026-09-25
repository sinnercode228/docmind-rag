"""Safe URL fetching for web-page ingestion (scheme allow-list, SSRF guard, size cap)."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from docmind.errors import DocumentTooLargeError, UnsafeURLError

Resolver = Callable[[str], Awaitable[list[str]]]

USER_AGENT = "DocMindBot/0.1 (+https://github.com/sinnercode228/docmind-rag)"


@dataclass(slots=True, frozen=True)
class FetchedResource:
    url: str
    data: bytes
    content_type: str | None


async def default_resolver(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%")[0])
    return ip.is_global and not ip.is_multicast


async def ensure_public_url(url: str, resolver: Resolver = default_resolver) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"}:
        raise UnsafeURLError("Only http(s) URLs can be ingested")
    if not parts.hostname:
        raise UnsafeURLError("URL has no host")
    if parts.username or parts.password:
        raise UnsafeURLError("URLs with credentials are not allowed")
    try:
        addresses = await resolver(parts.hostname)
    except OSError as exc:
        raise UnsafeURLError(f"Cannot resolve host {parts.hostname!r}") from exc
    if not addresses or not all(_is_public(a) for a in addresses):
        raise UnsafeURLError("URL resolves to a private or reserved address")
    return parts.geturl()


async def fetch_url(
    url: str,
    *,
    max_bytes: int,
    timeout_s: float,
    allow_private: bool = False,
    resolver: Resolver = default_resolver,
    transport: httpx.AsyncBaseTransport | None = None,
    max_redirects: int = 5,
) -> FetchedResource:
    """Download ``url`` while re-validating every redirect hop against the SSRF guard."""
    current = url
    async with httpx.AsyncClient(
        timeout=timeout_s,
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT},
        transport=transport,
    ) as client:
        for _ in range(max_redirects + 1):
            if not allow_private:
                current = await ensure_public_url(current, resolver)
            async with client.stream("GET", current) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise UnsafeURLError("Redirect without Location header")
                    current = str(response.url.join(location))
                    continue
                response.raise_for_status()
                declared = int(response.headers.get("content-length") or 0)
                if declared > max_bytes:
                    raise DocumentTooLargeError(f"Remote document exceeds {max_bytes} bytes")
                buffer = bytearray()
                async for piece in response.aiter_bytes():
                    buffer.extend(piece)
                    if len(buffer) > max_bytes:
                        raise DocumentTooLargeError(f"Remote document exceeds {max_bytes} bytes")
                return FetchedResource(
                    url=str(response.url),
                    data=bytes(buffer),
                    content_type=response.headers.get("content-type"),
                )
    raise UnsafeURLError("Too many redirects")
