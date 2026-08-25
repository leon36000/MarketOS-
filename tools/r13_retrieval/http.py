"""Bounded HTTPS transport and content-type helpers."""
from __future__ import annotations

import mimetypes
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Sequence

from .core import FetchResponse, Fetcher, RetrievalError


class _BoundedRedirectHandler(urllib.request.HTTPRedirectHandler):
    max_redirections = 8


def default_fetch(
    url: str,
    *,
    timeout: float,
    user_agent: str,
    max_bytes: int = 20_000_000,
) -> FetchResponse:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": (
                "text/html,application/xhtml+xml,application/pdf,text/plain,"
                "application/json,text/markdown,*/*;q=0.1"
            ),
            "Accept-Encoding": "identity",
        },
        method="GET",
    )
    opener = urllib.request.build_opener(_BoundedRedirectHandler())
    with opener.open(request, timeout=timeout) as response:
        status = int(getattr(response, "status", response.getcode()))
        content_type = response.headers.get("Content-Type", "application/octet-stream")
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise RetrievalError(f"response exceeds max_bytes={max_bytes}")
        headers = {
            key.lower(): value
            for key, value in response.headers.items()
            if key.lower() in {"etag", "last-modified", "content-length", "content-type"}
        }
        return FetchResponse(
            status=status,
            final_url=response.geturl(),
            content_type=content_type,
            body=data,
            headers=headers,
        )


def _extension(content_type: str, final_url: str) -> str:
    media_type = content_type.split(";", 1)[0].strip().lower()
    known = {
        "text/html": ".html",
        "application/xhtml+xml": ".html",
        "application/pdf": ".pdf",
        "application/json": ".json",
        "text/plain": ".txt",
        "text/markdown": ".md",
    }
    if media_type in known:
        return known[media_type]
    path_ext = Path(urllib.parse.urlsplit(final_url).path).suffix
    if re.fullmatch(r"\.[A-Za-z0-9]{1,8}", path_ext or ""):
        return path_ext.lower()
    return mimetypes.guess_extension(media_type) or ".bin"


def _matches_content_type(actual: str, expected: Sequence[str]) -> bool:
    media_type = actual.split(";", 1)[0].strip().lower()
    return any(
        media_type == item.lower() or media_type.startswith(item.lower().rstrip("*"))
        for item in expected
    )


def _invoke_fetcher(
    fetcher: Fetcher,
    url: str,
    *,
    timeout: float,
    user_agent: str,
    max_bytes: int,
) -> FetchResponse:
    try:
        return fetcher(url, timeout=timeout, user_agent=user_agent, max_bytes=max_bytes)
    except TypeError as exc:
        # Tests and injected fetchers may intentionally implement the minimal contract.
        if "max_bytes" not in str(exc):
            raise
        return fetcher(url, timeout=timeout, user_agent=user_agent)
