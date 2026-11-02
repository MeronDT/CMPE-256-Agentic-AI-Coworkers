"""Polite HTTP fetching with a disk cache. Fetched pages are data and are never executed."""
from __future__ import annotations

import hashlib
import json
import re

import httpx
import trafilatura

from . import config

MAX_BYTES = 3_000_000


def http_get(url: str, *, agent: str = config.USER_AGENT, timeout: float = 20.0) -> httpx.Response:
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Refusing non-http URL: {url}")
    return httpx.get(url, headers={"User-Agent": agent}, follow_redirects=True, timeout=timeout)


def page_date(html: str, meta) -> str:
    """Prefer an explicit datePublished, since some sites give every page one template date."""
    match = re.search(r'"datePublished"\s*:\s*"(\d{4}-\d{2}-\d{2})', html)
    if match:
        return match.group(1)
    return (meta.date if meta else "") or ""


def fetch_page(url: str) -> dict | None:
    """Return {"text", "title", "date"} for an article page, or None if it can't be read."""
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = config.CACHE_DIR / f"{hashlib.sha256(url.encode()).hexdigest()[:24]}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        resp = http_get(url)
    except (httpx.HTTPError, ValueError):
        return None
    if resp.status_code != 200 or len(resp.content) > MAX_BYTES:
        return None
    # Bytes, not resp.text: trafilatura detects the encoding better than httpx's default.
    text = trafilatura.extract(resp.content, include_comments=False, include_tables=False) or ""
    meta = trafilatura.extract_metadata(resp.content)
    page = {"text": text, "title": (meta.title if meta else "") or "", "date": page_date(resp.text, meta)}
    path.write_text(json.dumps(page), encoding="utf-8")
    return page


def url_ok(url: str) -> bool:
    """Check a link is real. DOIs go through Crossref, because publishers like ACM return 403 to scripts."""
    doi = re.match(r"https?://(?:dx\.)?doi\.org/(10\..+)", url)
    try:
        if doi:
            return http_get(f"https://api.crossref.org/works/{doi.group(1)}", agent=config.CROSSREF_AGENT,
                            timeout=15.0).status_code == 200
        return http_get(url, timeout=15.0).status_code == 200
    except (httpx.HTTPError, ValueError):
        return False
