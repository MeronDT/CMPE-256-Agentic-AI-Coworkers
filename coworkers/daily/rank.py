"""Local pre-ranking, reading-time estimates and top-3 selection. None of this uses the LLM."""
from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime
from itertools import combinations

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .. import config


def tag_topics(title: str, text: str) -> list[str]:
    title, text = title.lower(), text.lower()
    tags = []
    for topic, keywords in config.TOPIC_KEYWORDS.items():
        in_title = any(k in title for k in keywords)
        in_text = sum(text.count(k) for k in keywords)
        if in_title or in_text >= 2:
            tags.append(topic)
    return tags


def prerank(candidates: list[dict], weights: dict[str, float], as_of: date) -> list[dict]:
    """Score articles by interest match, topic weight, source authority and freshness."""
    if not candidates:
        return []
    query = " ".join(" ".join(config.TOPIC_KEYWORDS[t]) for t, w in weights.items()
                     if t in config.TOPIC_KEYWORDS for _ in range(max(1, round(w * 2))))
    docs = [f"{c['title']} {c['title']} {c['snippet']}" for c in candidates]
    matrix = TfidfVectorizer(stop_words="english", max_features=6000).fit_transform(docs + [query])
    sims = cosine_similarity(matrix[:-1], matrix[-1]).ravel()
    top = float(sims.max()) or 1.0
    scored = []
    for item, sim in zip(candidates, sims):
        topics = tag_topics(item["title"], item["snippet"] + " " + item["text"][:3000])
        topic_score = max((weights.get(t, 1.0) for t in topics), default=0.0) / 2.0
        age = (as_of - datetime.strptime(item["published"][:10], "%Y-%m-%d").date()).days
        freshness = max(0.0, 1 - age / max(config.WINDOW_DAYS, 1))
        pre = 0.45 * (sim / top) + 0.25 * topic_score + 0.15 * item["authority"] + 0.15 * freshness
        scored.append({**item, "topics": topics, "pre_score": round(float(pre), 4)})
    return sorted(scored, key=lambda c: c["pre_score"], reverse=True)


def shortlist(ranked: list[dict], size: int = config.SHORTLIST_SIZE, per_source: int = 3) -> list[dict]:
    picked, counts = [], {}
    for item in ranked:
        if counts.get(item["source"], 0) < per_source:
            picked.append(item)
            counts[item["source"]] = counts.get(item["source"], 0) + 1
        if len(picked) == size:
            break
    return picked


def minutes_for(item: dict) -> int:
    """Reading time, with long pieces capped because the brief assigns the key sections."""
    if item["kind"] == "abstract":
        return config.MAX_MINUTES_PER_ARTICLE
    words = len(re.findall(r"\w+", item["text"]))
    return max(3, min(config.MAX_MINUTES_PER_ARTICLE, round(words / config.READING_WPM)))


def session_minutes(items: list[dict]) -> int:
    """Article time plus one minute each for the summary and recall question."""
    return sum(minutes_for(i) + 1 for i in items)


def choose_articles(ranked: list[dict], keep: list[dict], rejected: set[str], count: int = 3) -> list[dict]:
    """Best set of distinct-source articles, preferring a 15-20 minute session."""
    keep_urls = {k["url"] for k in keep}
    pool = [c for c in ranked if c["url"] not in rejected and c["url"] not in keep_urls][:9]
    need = count - len(keep)
    if need <= 0:
        return keep[:count]
    # A full set matters most. Sources stay distinct when possible, then one may repeat.
    for size in range(min(need, len(pool)), 0, -1):
        for per_source in (1, config.MAX_PER_SOURCE):
            best, best_value = None, float("-inf")
            for combo in combinations(pool, size):
                chosen = keep + list(combo)
                if max(Counter(c["source"] for c in chosen).values()) > per_source:
                    continue
                topics = {t for c in chosen for t in c["topics"][:2]}
                minutes = session_minutes(chosen)
                miss = max(0, config.READING_MIN - minutes) + max(0, minutes - config.READING_MAX)
                value = sum(c["final_score"] for c in chosen) + 0.05 * len(topics) - 0.08 * miss
                if value > best_value:
                    best, best_value = chosen, value
            if best is not None:
                return best
    return keep
