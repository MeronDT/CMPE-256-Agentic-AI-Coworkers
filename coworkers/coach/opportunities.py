"""Find internships, jobs, research leads and venture signals, and score their fit."""
from __future__ import annotations

import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import feedparser
import httpx

from .. import config
from ..daily.sources import from_arxiv, strip_tags
from ..web import http_get

SENIOR_RE = re.compile(r"\b(senior|staff|principal|lead|manager|director|head of|sr\.?|architect|phd)\b", re.I)
ENTRY_RE = re.compile(r"\b(intern|internship|new grad|new graduate|university grad|early career|graduate|entry)\b", re.I)
ROLE_RE = re.compile(r"\b(software|backend|back-end|systems|infrastructure|platform|cloud|full[- ]?stack|developer|swe)\b", re.I)
# The learner is an MS student aiming for summer, so these titles can never fit.
OFF_TARGET_RE = re.compile(r"\b(high school|winter|fall|spring)\b", re.I)


def _opp(kind: str, title: str, org: str, url: str, *, location: str = "", posted: str = "", text: str = "",
         notes: str = "") -> dict:
    return {"id": hashlib.sha256(url.encode()).hexdigest()[:16], "kind": kind, "title": title, "org": org, "url": url,
            "location": location, "posted": posted, "text": text, "notes": notes}


def _from_epoch(seconds: float | None) -> str:
    if not seconds:
        return ""
    return datetime.fromtimestamp(seconds, tz=timezone.utc).date().isoformat()


def _classify(title: str) -> str | None:
    """Return internship, job or None. Only software roles at intern or entry level qualify."""
    if SENIOR_RE.search(title) or OFF_TARGET_RE.search(title) or not ROLE_RE.search(title):
        return None
    if re.search(r"\bintern(ship)?\b", title, re.I):
        return "internship"
    return "job" if ENTRY_RE.search(title) else None


def from_simplify(term: str) -> list[dict]:
    resp = http_get(config.SIMPLIFY_URL, timeout=30.0)
    resp.raise_for_status()
    items = []
    for row in resp.json():
        if not (row.get("active") and row.get("is_visible")) or term not in row.get("terms", []):
            continue
        if row.get("category") not in {"Software", "Software Engineering"} or not ROLE_RE.search(row.get("title", "")):
            continue
        if SENIOR_RE.search(row["title"]) or OFF_TARGET_RE.search(row["title"]):
            continue
        items.append(_opp("internship", row["title"], row.get("company_name", ""), row["url"],
                          location="; ".join(row.get("locations", [])[:3]), posted=_from_epoch(row.get("date_posted")),
                          notes=f"Sponsorship: {row.get('sponsorship', 'unknown')}"))
    return items


def from_greenhouse(board: str) -> list[dict]:
    resp = http_get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true")
    resp.raise_for_status()
    items = []
    for job in resp.json().get("jobs", []):
        kind = _classify(job.get("title", ""))
        if kind:
            items.append(_opp(kind, job["title"], board.title(), job["absolute_url"],
                              location=(job.get("location") or {}).get("name", ""),
                              posted=(job.get("updated_at") or "")[:10], text=strip_tags(strip_tags(job.get("content", "")))))
    return items


def from_lever(board: str) -> list[dict]:
    resp = http_get(f"https://api.lever.co/v0/postings/{board}?mode=json")
    resp.raise_for_status()
    items = []
    for job in resp.json():
        kind = _classify(job.get("text", ""))
        if kind:
            created = job.get("createdAt")
            items.append(_opp(kind, job["text"], board.title(), job["hostedUrl"],
                              location=(job.get("categories") or {}).get("location", ""),
                              posted=_from_epoch(created / 1000 if created else None),
                              text=job.get("descriptionPlain", "")))
    return items


def from_ashby(board: str) -> list[dict]:
    resp = http_get(f"https://api.ashbyhq.com/posting-api/job-board/{board}")
    resp.raise_for_status()
    items = []
    for job in resp.json().get("jobs", []):
        kind = _classify(job.get("title", ""))
        if kind:
            items.append(_opp(kind, job["title"], board.title(), job["jobUrl"], location=job.get("location", ""),
                              posted=(job.get("publishedAt") or "")[:10], text=job.get("descriptionPlain", "")))
    return items


def research_leads() -> list[dict]:
    leads = []
    for paper in from_arxiv():
        leads.append(_opp("research", paper["title"], "arXiv", paper["url"], posted=paper["published"],
                          text=paper["text"], notes="Research lead: a recent paper to read or extend, not an open position."))
    return leads


def venture_signals() -> list[dict]:
    feed = feedparser.parse(http_get(config.HN_SHOW_FEED).content)
    signals = []
    for entry in feed.entries[:40]:
        parsed = entry.get("published_parsed")
        posted = f"{parsed.tm_year:04d}-{parsed.tm_mon:02d}-{parsed.tm_mday:02d}" if parsed else ""
        signals.append(_opp("venture", entry.get("title", ""), "Hacker News", entry.get("link", ""), posted=posted,
                            text=strip_tags(entry.get("summary", "")),
                            notes="Market signal: what builders are launching, not a funded opportunity."))
    return signals


def _has_term(term: str, text: str) -> bool:
    """Match at a word start, so "rest" doesn't hit "interest" but "concurren" hits "concurrency"."""
    return re.search(rf"(?<![a-z0-9]){re.escape(term.lower())}", text) is not None


def fit_score(item: dict, profile: dict, skill_terms: dict[str, list[str]]) -> float:
    """0-1 fit from role match, location and how much of the posting the learner's skills cover."""
    milestone = profile["milestone"]
    title, text = item["title"].lower(), item["text"].lower()
    if item["kind"] == "venture":
        hits = sum(_has_term(term, f"{title} {text}") for term in profile["venture_interests"])
        return round(min(1.0, 0.2 + 0.4 * hits), 3)
    role = 1.0 if any(k in title for k in milestone["role_keywords"]) else 0.5
    where = item["location"].lower()
    location = 1.0 if any(re.search(rf"\b{re.escape(p.lower())}\b", where) for p in milestone["preferred_locations"]) else 0.3
    strong = [s for s, level in profile["skills"].items() if level >= 0.5]
    wanted = [s for s, terms in skill_terms.items() if any(_has_term(t, text) for t in terms)]
    overlap = len(set(wanted) & set(strong)) / len(wanted) if wanted else 0.5
    if item["kind"] == "research":
        return round(0.3 + 0.7 * overlap, 3)
    bonus = 0.1 if item["kind"] == "internship" else 0.0
    return round(min(1.0, 0.4 * role + 0.3 * location + 0.2 * overlap + bonus), 3)


SKILL_TERMS = {
    "dsa": ["algorithm", "data structure"],
    "system-design": ["system design", "scalable", "architecture"],
    "concurrency": ["concurren", "multithread", "parallel"],
    "databases-sql": ["sql", "database", "postgres"],
    "distributed-systems": ["distributed"],
    "cloud-aws": ["aws", "cloud", "gcp", "azure", "kubernetes"],
    "networking": ["networking", "tcp", "http"],
    "os-internals": ["operating system", "linux", "kernel"],
    "api-design": ["api", "rest", "grpc"],
    "testing-ci": ["testing", "ci/cd", "unit test"],
    "python": ["python"],
    "cpp": ["c++"],
    "java": ["java "],
    "javascript-react": ["javascript", "typescript", "react"],
    "ai-engineering": ["llm", "machine learning", "generative ai"],
}


def scout(profile: dict) -> tuple[list[dict], list[str]]:
    term = profile["milestone"]["target_term"]
    jobs = (
        [("Simplify", lambda: from_simplify(term)), ("arXiv", research_leads), ("Hacker News", venture_signals)]
        + [(f"Greenhouse/{b}", lambda b=b: from_greenhouse(b)) for b in config.GREENHOUSE_BOARDS]
        + [(f"Lever/{b}", lambda b=b: from_lever(b)) for b in config.LEVER_BOARDS]
        + [(f"Ashby/{b}", lambda b=b: from_ashby(b)) for b in config.ASHBY_BOARDS]
    )
    found: list[dict] = []
    warnings: list[str] = []

    def run(job):
        name, fn = job
        try:
            return fn(), None
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            return [], f"{name} was unavailable: {str(exc)[:100]}"

    with ThreadPoolExecutor(max_workers=8) as pool:
        for items, error in pool.map(run, jobs):
            found.extend(items)
            if error:
                warnings.append(error)
    unique = {item["url"]: item for item in found if item["url"]}
    for item in unique.values():
        item["fit"] = fit_score(item, profile, SKILL_TERMS)
    return sorted(unique.values(), key=lambda i: (i["fit"], i["posted"]), reverse=True), warnings


def top_by_kind(items: list[dict]) -> dict[str, list[dict]]:
    limits = {"internship": 8, "job": 4, "research": 3, "venture": 3}
    return {kind: [i for i in items if i["kind"] == kind][:limit] for kind, limit in limits.items()}
