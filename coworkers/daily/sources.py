"""Article discovery across RSS, sitemaps, listing pages, Crossref and arXiv."""
from __future__ import annotations

import html
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from time import struct_time

import feedparser
import httpx

from .. import config
from ..web import fetch_page, http_get

TAG_RE = re.compile(r"<[^>]+>")
SITEMAP_ENTRY_RE = re.compile(r"<url>(.*?)</url>", re.S)


def strip_tags(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", text or ""))).strip()


def _iso(parsed: struct_time | None) -> str:
    return f"{parsed.tm_year:04d}-{parsed.tm_mon:02d}-{parsed.tm_mday:02d}" if parsed else ""


def _article(url: str, title: str, source: str, published: str, authority: float, *, snippet: str = "",
             text: str = "", kind: str = "page") -> dict:
    return {"url": url, "title": strip_tags(title), "source": source, "published": published, "authority": authority,
            "snippet": strip_tags(snippet)[:600], "text": text, "kind": kind}


def from_feed(spec: dict) -> list[dict]:
    feed = feedparser.parse(http_get(spec["url"]).content)
    items = []
    for entry in feed.entries[:40]:
        published = _iso(entry.get("published_parsed") or entry.get("updated_parsed"))
        items.append(_article(entry.get("link", ""), entry.get("title", ""), spec["source"], published,
                              spec["authority"], snippet=entry.get("summary", "")))
    return items


def from_sitemap(spec: dict, as_of: date, limit: int = 15) -> list[dict]:
    resp = http_get(spec["url"])
    resp.raise_for_status()
    pattern = re.compile(spec["pattern"])
    cutoff = (as_of - timedelta(days=45)).isoformat()
    entries = []
    for block in SITEMAP_ENTRY_RE.findall(resp.text):
        loc = re.search(r"<loc>\s*([^<\s]+)", block)
        lastmod = re.search(r"<lastmod>\s*([^<\s]+)", block)
        if not loc or not pattern.search(loc.group(1)):
            continue
        modified = lastmod.group(1)[:10] if lastmod else ""
        if modified >= cutoff:
            entries.append((modified, loc.group(1)))
    entries.sort(reverse=True)
    return _from_pages([url for _, url in entries[:limit]], spec)


def from_listing(spec: dict) -> list[dict]:
    resp = http_get(spec["url"])
    resp.raise_for_status()
    paths = sorted(set(re.findall(spec["pattern"], resp.text)))
    return _from_pages([spec["base"] + path for path in paths[:15]], spec)


def _from_pages(urls: list[str], spec: dict) -> list[dict]:
    """Sitemap lastmod is an edit date, so the publication date comes from the page itself."""
    with ThreadPoolExecutor(max_workers=6) as pool:
        pages = list(pool.map(fetch_page, urls))
    items = []
    for url, page in zip(urls, pages):
        if page and page["date"] and page["text"]:
            items.append(_article(url, page["title"], spec["source"], page["date"][:10], spec["authority"],
                                  snippet=page["text"][:600], text=page["text"]))
    return items


def from_crossref(spec: dict) -> list[dict]:
    url = (f"https://api.crossref.org/journals/{spec['issn']}/works?sort=published&order=desc&rows=25"
           "&select=title,DOI,published,abstract,URL")
    resp = http_get(url, agent=config.CROSSREF_AGENT)
    resp.raise_for_status()
    items = []
    for work in resp.json()["message"]["items"]:
        parts = (work.get("published") or {}).get("date-parts", [[]])[0]
        if len(parts) < 3 or not work.get("title"):
            continue
        abstract = strip_tags(work.get("abstract", ""))
        published = f"{parts[0]:04d}-{parts[1]:02d}-{parts[2]:02d}"
        items.append(_article(work["URL"], work["title"][0], spec["source"], published, spec["authority"],
                              snippet=abstract, text=abstract, kind="abstract"))
    return items


def from_acm() -> list[dict]:
    """Crossref rate-limits parallel requests, so the journals are fetched one at a time."""
    items: list[dict] = []
    for spec in config.CROSSREF_JOURNALS:
        items.extend(from_crossref(spec))
        time.sleep(1.5)
    return items


def from_arxiv() -> list[dict]:
    query = "+OR+".join(f"cat:{cat}" for cat in config.ARXIV_CATEGORIES)
    url = f"https://export.arxiv.org/api/query?search_query={query}&sortBy=submittedDate&sortOrder=descending&max_results=60"
    feed = feedparser.parse(http_get(url, timeout=30.0).content)
    items = []
    for entry in feed.entries:
        abstract = strip_tags(entry.get("summary", ""))
        items.append(_article(entry.get("link", ""), entry.get("title", ""), "arXiv",
                              _iso(entry.get("published_parsed")), 0.8, snippet=abstract, text=abstract, kind="abstract"))
    return items


def fetch_candidates(as_of: date) -> tuple[list[dict], list[str]]:
    """Collect recent articles. A source that fails is reported, never fatal."""
    jobs = (
        [(spec["source"], lambda s=spec: from_feed(s)) for spec in config.FEEDS]
        + [(spec["source"], lambda s=spec: from_sitemap(s, as_of)) for spec in config.SITEMAPS]
        + [(spec["source"], lambda s=spec: from_listing(s)) for spec in config.LISTING_PAGES]
        + [("ACM", from_acm), ("arXiv", from_arxiv)]
    )
    candidates: list[dict] = []
    warnings: list[str] = []

    def run(job):
        name, fn = job
        try:
            return name, fn(), None
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            return name, [], str(exc)[:120]

    with ThreadPoolExecutor(max_workers=8) as pool:
        for name, items, error in pool.map(run, jobs):
            candidates.extend(i for i in items if i["url"] and i["title"])
            if error:
                warnings.append(f"{name} was unavailable: {error}")
            elif not items:
                warnings.append(f"{name} returned no articles")
    return candidates, warnings


def hydrate(candidates: list[dict]) -> list[dict]:
    """Attach full text to shortlisted articles and drop any that can't be read."""
    def load(item: dict) -> dict | None:
        if item["text"]:
            return item
        page = fetch_page(item["url"])
        if not page or not page["text"]:
            return None
        return {**item, "text": page["text"]}

    with ThreadPoolExecutor(max_workers=6) as pool:
        loaded = list(pool.map(load, candidates))
    return [item for item in loaded if item and len(item["text"].split()) >= config.MIN_WORDS]


def in_window(published: str, as_of: date) -> bool:
    try:
        when = datetime.strptime(published[:10], "%Y-%m-%d").date()
    except ValueError:
        return False
    return as_of - timedelta(days=config.WINDOW_DAYS) <= when <= as_of
