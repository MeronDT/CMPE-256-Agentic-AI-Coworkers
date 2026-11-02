"""DailyTechUpgradeAgent: a LangGraph workflow that produces one learning brief."""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from datetime import date
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .. import config
from ..llm import LLMClient, wrap_untrusted
from ..memory import Store
from ..web import url_ok
from . import rank, sources
from .render import render_brief
from .schemas import RankOut, SummaryOut

RANK_SYSTEM = (
    "You curate technical reading for one learner. Score each article for relevance to the learner and for "
    "technical depth. Favor articles that explain how something works, and penalize product announcements, "
    "funding news and marketing. Favor material that teaches something the learner has not already covered."
)
SUMMARY_SYSTEM = (
    "You write a daily technical learning brief for one learner. Use only facts in the article. Each insight "
    "needs an evidence_quote copied exactly from the article text. The new concept must be something the "
    "learner has not already logged, and must come from this article."
)


class State(TypedDict, total=False):
    as_of: str
    is_replay: bool
    profile: dict
    weights: dict
    known_concepts: list
    candidates: list
    pool_size: int
    ranked: list
    selected: list
    summaries: dict
    attempts: dict
    failures: dict
    rejected: list
    verification: dict
    warnings: list
    brief: dict


def normalize_words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).split()


def quote_found(quote: str, text: str) -> bool:
    return " ".join(normalize_words(quote)) in " ".join(normalize_words(text))


def check_article(item: dict, summary: dict, as_of: date, known: list[str], check_url: Callable[[str], bool]) -> dict:
    """Deterministic checks. A brief item ships only if every one passes."""
    quotes = [i["evidence_quote"] for i in summary["insights"]]
    grounded = [quote_found(q, item["text"]) and len(normalize_words(q)) >= 4 for q in quotes]
    return {
        "url_ok": check_url(item["url"]),
        "date_in_window": sources.in_window(item["published"], as_of),
        "title_present": bool(item["title"]),
        "insight_count_ok": len(quotes) == 3,
        "quotes_grounded": sum(grounded),
        "quotes_total": len(quotes),
        "all_quotes_grounded": bool(quotes) and all(grounded),
        "concept_is_new": summary["new_concept_name"].strip().lower() not in {k.lower() for k in known},
    }


def passed(check: dict) -> bool:
    return all(check[k] for k in ("url_ok", "date_in_window", "title_present", "insight_count_ok",
                                  "all_quotes_grounded", "concept_is_new"))


def build_graph(llm: LLMClient, store: Store, *, fetch: Callable = sources.fetch_candidates,
                hydrate: Callable = sources.hydrate, check_url: Callable[[str], bool] = url_ok):
    def learner_context(state: State) -> str:
        profile = state["profile"]
        top = sorted(state["weights"].items(), key=lambda kv: -kv[1])[:6]
        return (f"Learner: {profile['degree']}. Milestone: {profile['milestone']['title']}.\n"
                f"Priority topics: {', '.join(t for t, _ in top)}.\n"
                f"Concepts already logged: {', '.join(state['known_concepts'][-30:]) or 'none yet'}.")

    def load_context(state: State) -> dict:
        profile = state["profile"]
        return {"weights": store.topic_weights(profile["interests"]),
                "known_concepts": [c["name"] for c in store.concepts() if c["learned_on"] < state["as_of"]],
                "attempts": {}, "failures": {}, "rejected": [], "summaries": {}, "verification": {},
                "selected": [], "warnings": []}

    def discover(state: State) -> dict:
        as_of = date.fromisoformat(state["as_of"])
        found, warnings = fetch(as_of)
        seen = store.seen_urls(before=state["as_of"])
        fresh, urls = [], set()
        for item in found:
            if item["url"] not in seen and item["url"] not in urls and sources.in_window(item["published"], as_of):
                fresh.append(item)
                urls.add(item["url"])
        return {"candidates": fresh, "pool_size": len(found), "warnings": state["warnings"] + warnings}

    def shortlist_node(state: State) -> dict:
        as_of = date.fromisoformat(state["as_of"])
        scored = rank.prerank(state["candidates"], state["weights"], as_of)
        # Read more than we need, since some pages turn out to be too short to use.
        readable = hydrate(rank.shortlist(scored, size=config.SHORTLIST_SIZE + 6))
        scored_again = rank.prerank(readable, state["weights"], as_of)
        return {"ranked": rank.shortlist(scored_again)}

    def rank_node(state: State) -> dict:
        items = state["ranked"]
        if not items:
            return {"ranked": [], "warnings": state["warnings"] + ["No readable articles in the date window."]}
        listing = "\n\n".join(
            f"[{i}] {c['title']} ({c['source']}, {c['published']})\n{c['text'][:900]}" for i, c in enumerate(items))
        out = llm.parse(RankOut, f"{learner_context(state)}\n\nArticles:\n{wrap_untrusted(listing)}",
                        system=RANK_SYSTEM, purpose="daily.rank", max_tokens=1800)
        scores = {s.index: s for s in out.scores}
        ranked = []
        for i, item in enumerate(items):
            score = scores.get(i)
            if score is None or score.technical_depth < 5:
                continue
            final = 0.6 * score.relevance / 10 + 0.3 * score.technical_depth / 10 + 0.1 * item["pre_score"]
            ranked.append({**item, "relevance": score.relevance, "technical_depth": score.technical_depth,
                           "rank_reason": score.reason, "final_score": round(final, 4)})
        return {"ranked": sorted(ranked, key=lambda c: c["final_score"], reverse=True)}

    def select(state: State) -> dict:
        verified = [c for c in state["selected"] if state["verification"].get(c["url"], {}).get("passed")]
        pending = [c for c in state["selected"] if c["url"] not in {v["url"] for v in verified}
                   and c["url"] not in state["rejected"]]
        return {"selected": rank.choose_articles(state["ranked"], verified + pending, set(state["rejected"]))}

    def summarize(state: State) -> dict:
        summaries = dict(state["summaries"])
        attempts = dict(state["attempts"])
        context = learner_context(state)
        for item in state["selected"]:
            if state["verification"].get(item["url"], {}).get("passed"):
                continue
            problem = state["failures"].get(item["url"])
            note = f"\nYour last attempt failed these checks: {problem}. Fix them." if problem else ""
            prompt = (f"{context}\n\nReading time for this article: {rank.minutes_for(item)} minutes.\n"
                      f"Title: {item['title']}\nSource: {item['source']}\n\n"
                      f"{wrap_untrusted(item['text'][:12000])}{note}")
            out = llm.parse(SummaryOut, prompt, system=SUMMARY_SYSTEM, purpose="daily.summarize", max_tokens=1500)
            summaries[item["url"]] = out.model_dump()
            attempts[item["url"]] = attempts.get(item["url"], 0) + 1
        return {"summaries": summaries, "attempts": attempts}

    def verify(state: State) -> dict:
        as_of = date.fromisoformat(state["as_of"])
        verification = dict(state["verification"])
        failures = dict(state["failures"])
        rejected = list(state["rejected"])
        for item in state["selected"]:
            url = item["url"]
            if verification.get(url, {}).get("passed"):
                continue
            check = check_article(item, state["summaries"][url], as_of, state["known_concepts"], check_url)
            check["passed"] = passed(check)
            verification[url] = check
            if check["passed"]:
                continue
            failures[url] = ", ".join(k for k, v in check.items() if v is False)
            if state["attempts"].get(url, 0) > config.MAX_SUMMARY_RETRIES or not check["url_ok"]:
                rejected.append(url)
        return {"verification": verification, "failures": failures, "rejected": rejected}

    def after_verify(state: State) -> str:
        selected = state["selected"]
        passing = [c for c in selected if state["verification"][c["url"]]["passed"]]
        awaiting_retry = [c for c in selected if c not in passing and c["url"] not in state["rejected"]]
        if awaiting_retry:
            return "select"
        if len(passing) >= 3:
            return "write"
        # Only loop if select can add something. Otherwise it would change nothing and never end.
        used = {c["url"] for c in passing}
        per_source = Counter(c["source"] for c in passing)
        can_add = any(c["url"] not in state["rejected"] and c["url"] not in used
                      and per_source[c["source"]] < config.MAX_PER_SOURCE for c in state["ranked"])
        return "select" if can_add else "write"

    def write(state: State) -> dict:
        verification = state["verification"]
        final = [c for c in state["selected"] if verification[c["url"]]["passed"]]
        warnings = list(state["warnings"])
        if len(final) < 3:
            warnings.append(f"Only {len(final)} of 3 articles passed verification today.")
        items = []
        for item in final:
            items.append({
                **{k: item[k] for k in ("title", "source", "published", "url", "kind", "topics", "relevance",
                                        "technical_depth", "rank_reason", "final_score")},
                "minutes": rank.minutes_for(item), **state["summaries"][item["url"]],
                "verification": verification[item["url"]],
            })
        brief = {
            "date": state["as_of"], "is_replay": state["is_replay"], "items": items,
            "total_minutes": rank.session_minutes(final), "pool_size": state["pool_size"],
            "fresh_candidates": len(state["candidates"]), "warnings": warnings,
            "attempts": state["attempts"], "rejected": state["rejected"], "ranked_count": len(state["ranked"]),
            "failures": {url: state["failures"].get(url, "") for url in state["rejected"]},
        }
        store.clear_day(state["as_of"])
        for entry in items:
            store.mark_seen(entry["url"], entry["title"], entry["source"], entry["published"], state["as_of"])
            store.add_concept(entry["new_concept_name"], entry["new_concept_explanation"], entry["recall_question"],
                              entry["recall_answer"], entry["url"], state["as_of"])
        brief["concepts_total"] = len(store.concepts())
        store.save_brief(state["as_of"], state["is_replay"], brief)
        render_brief(brief)
        return {"brief": brief}

    graph = StateGraph(State)
    for name, fn in [("load_context", load_context), ("discover", discover), ("shortlist", shortlist_node),
                     ("rank", rank_node), ("select", select), ("summarize", summarize), ("verify", verify),
                     ("write", write)]:
        graph.add_node(name, fn)
    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "discover")
    graph.add_edge("discover", "shortlist")
    graph.add_edge("shortlist", "rank")
    graph.add_edge("rank", "select")
    graph.add_edge("select", "summarize")
    graph.add_edge("summarize", "verify")
    graph.add_conditional_edges("verify", after_verify, {"select": "select", "write": "write"})
    graph.add_edge("write", END)
    return graph.compile()


def run_brief(llm: LLMClient, store: Store, profile: dict, as_of: date, *, is_replay: bool = False, **deps) -> dict:
    result = build_graph(llm, store, **deps).invoke(
        {"as_of": as_of.isoformat(), "is_replay": is_replay, "profile": profile}, {"recursion_limit": 80})
    return result["brief"]
