"""Measure both agents and write eval/results.json and eval/RESULTS.md.

Checks that need no LLM always run. The others run when an API key is set.
"""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coworkers import config  # noqa: E402
from coworkers.coach.graph import evaluate_answer, load_resources  # noqa: E402
from coworkers.coach.schemas import JobSkills  # noqa: E402
from coworkers.daily import rank, sources  # noqa: E402
from coworkers.daily.graph import quote_found  # noqa: E402
from coworkers.llm import OpenAILLM, wrap_untrusted  # noqa: E402
from coworkers.memory import Store  # noqa: E402
from coworkers.profile import load_profile  # noqa: E402
from coworkers.web import fetch_page, url_ok  # noqa: E402

HERE = Path(__file__).parent
SYSTEM_PERSONAS = {
    "SWE focus (this profile)": None,
    "ML research focus": {"machine learning": 2.0, "ai engineering": 1.6, "agents": 1.2},
    "Security focus": {"security": 2.0, "distributed systems": 0.7},
}


class Judged(BaseModel):
    supported: list[bool]


def daily_quality(store: Store, llm) -> dict:
    briefs = [b["payload"] for b in store.briefs()]
    items = [i for b in briefs for i in b["items"]]
    if not items:
        return {"briefs": 0}
    with ThreadPoolExecutor(max_workers=8) as pool:
        live = list(pool.map(lambda i: url_ok(i["url"]), items))
    quotes_total = sum(i["verification"]["quotes_total"] for i in items)
    quotes_ok = sum(i["verification"]["quotes_grounded"] for i in items)
    minutes = [b["total_minutes"] for b in briefs if len(b["items"]) == 3]
    in_range = sum(config.READING_MIN <= m <= config.READING_MAX for m in minutes)
    attempts = [a for b in briefs for a in b["attempts"].values()]
    urls = [i["url"] for i in items]
    result = {
        "briefs": len(briefs), "replayed": sum(b["is_replay"] for b in briefs), "articles": len(items),
        "full_briefs": sum(len(b["items"]) == 3 for b in briefs),
        "links_live_pct": round(100 * sum(live) / len(live), 1),
        "dates_in_window_pct": round(100 * sum(sources.in_window(i["published"], date.fromisoformat(b["date"]))
                                               for b in briefs for i in b["items"]) / len(items), 1),
        "quotes_grounded_pct": round(100 * quotes_ok / quotes_total, 1) if quotes_total else 0.0,
        "first_pass_verified_pct": round(100 * sum(a == 1 for a in attempts) / len(attempts), 1) if attempts else 0.0,
        "rejected_by_verifier": sum(len(b["rejected"]) for b in briefs),
        "reading_minutes": minutes, "reading_in_target_pct": round(100 * in_range / len(minutes), 1) if minutes else 0.0,
        "distinct_sources": len({i["source"] for i in items}), "repeated_articles": len(urls) - len(set(urls)),
        "concepts_logged": len(store.concepts()),
    }
    ratings = [f["rating"] for f in store.feedback()]
    result["user_ratings"] = len(ratings)
    if ratings:
        result["user_mean_rating"] = round(sum(ratings) / len(ratings), 2)
        result["user_useful_pct"] = round(100 * sum(r >= 4 for r in ratings) / len(ratings), 1)
    if llm:
        result.update(judge_faithfulness(llm, items))
    return result


def judge_faithfulness(llm, items: list[dict]) -> dict:
    """An independent read of whether each insight is supported by the article, not just its quote."""
    supported = total = 0
    for item in items:
        page = None if item["kind"] == "abstract" else fetch_page(item["url"])
        if not page:
            continue
        points = "\n".join(f"{n}. {i['point']}" for n, i in enumerate(item["insights"], 1))
        out = llm.parse(Judged, f"Claims:\n{points}\n\nArticle:\n{wrap_untrusted(page['text'][:9000])}",
                        system="For each numbered claim, decide if the article directly supports it. Return one boolean per claim.",
                        purpose="eval.faithfulness", model=config.EVAL_MODEL, max_tokens=300)
        supported += sum(out.supported)
        total += len(out.supported)
    return {"claims_judged": total, "claims_supported_pct": round(100 * supported / total, 1) if total else None}


def personalization(profile: dict) -> dict:
    """Same day, same articles, different learners: does the shortlist change the way it should?"""
    today = date.today()
    found, _ = sources.fetch_candidates(today)
    pool = {i["url"]: i for i in found if sources.in_window(i["published"], today)}
    base = dict(profile["interests"])
    lists, focus = {}, {}
    for name, change in SYSTEM_PERSONAS.items():
        weights = {**base, **(change or {})}
        picked = rank.shortlist(rank.prerank(list(pool.values()), weights, today))
        lists[name] = {i["url"] for i in picked}
        top = sorted(weights, key=weights.get, reverse=True)[:3]
        focus[name] = round(100 * sum(any(t in top for t in i["topics"]) for i in picked) / max(len(picked), 1), 1)
    names = list(lists)
    overlap = {f"{names[0]} vs {other}": round(100 * len(lists[names[0]] & lists[other]) / max(len(lists[names[0]]), 1), 1)
               for other in names[1:]}
    return {"pool": len(pool), "shortlist_overlap_pct": overlap, "shortlist_matches_own_top_topics_pct": focus}


def skill_extraction(llm) -> dict:
    posts = yaml.safe_load((HERE / "fixtures" / "job_posts.yaml").read_text(encoding="utf-8"))
    tp = fp = fn = 0
    for post in posts:
        out = llm.parse(JobSkills, f"Job post:\n{wrap_untrusted(post['text'])}",
                        system="List the skills from the allowed taxonomy this post explicitly asks for. Do not guess.",
                        purpose="eval.extraction", max_tokens=300)
        got, want = set(out.skills), set(post["skills"])
        tp += len(got & want)
        fp += len(got - want)
        fn += len(want - got)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"posts": len(posts), "precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3)}


def scoring_calibration(llm) -> dict:
    questions = yaml.safe_load((HERE / "fixtures" / "scoring.yaml").read_text(encoding="utf-8"))
    injection = yaml.safe_load((HERE / "fixtures" / "injection.yaml").read_text(encoding="utf-8"))["answer"]
    rows, repeat_diffs = [], []
    for q in questions:
        scores = {k: evaluate_answer(llm, q["question"], q["rubric"], q[k])["score"]
                  for k in ("strong", "partial", "wrong", "bluff")}
        scores["injection"] = evaluate_answer(llm, q["question"], q["rubric"], injection)["score"]
        again = evaluate_answer(llm, q["question"], q["rubric"], q["partial"])["score"]
        repeat_diffs.append(abs(again - scores["partial"]))
        rows.append({"question": q["question"][:60], **scores})
    ordered = sum(r["strong"] > r["partial"] > r["wrong"] for r in rows)
    return {
        "questions": len(rows), "scores": rows,
        "ordering_correct_pct": round(100 * ordered / len(rows), 1),
        "bluff_scored_below_strong_pct": round(100 * sum(r["bluff"] < r["strong"] for r in rows) / len(rows), 1),
        "injection_max_score": max(r["injection"] for r in rows),
        "repeat_mean_abs_diff": round(sum(repeat_diffs) / len(repeat_diffs), 1),
    }


def resources_check() -> dict:
    catalog = load_resources()
    with ThreadPoolExecutor(max_workers=8) as pool:
        ok = list(pool.map(lambda r: url_ok(r["url"]), catalog))
    return {"resources": len(catalog), "links_live_pct": round(100 * sum(ok) / len(ok), 1)}


def progress(store: Store) -> dict:
    reports = store.reports()
    real = [a for a in store.answers() if not a["simulated"]]
    skipped = sum(a["answer"].strip().lower() in {"", "skip", "idk", "i don't know", "pass"} for a in real)
    result = {"real_sessions": len(reports), "answers": len(real) - skipped, "skipped": skipped}
    if reports:
        result["readiness_first"] = reports[0]["readiness"]
        result["readiness_latest"] = reports[-1]["readiness"]
        result["measured_share_latest"] = reports[-1]["payload"]["readiness"]["measured_share"]
    history: dict[str, list[float]] = {}
    for row in store.skill_history():
        history.setdefault(row["skill"], []).append(row["score"])
    result["skills_retested"] = {s: {"first": v[0], "latest": v[-1]} for s, v in history.items() if len(v) > 1}
    return result


def to_markdown(r: dict) -> str:
    d, c = r["daily"], r["coach"]
    lines = ["# Evaluation results", "", f"Run on {r['date']}.", ""]
    lines += ["## DailyTechUpgradeAgent", ""]
    if d.get("briefs"):
        lines += [
            "| Measure | Result |", "|---|---|",
            f"| Briefs (replayed) | {d['briefs']} ({d['replayed']}) |",
            f"| Briefs with all 3 articles | {d['full_briefs']} |",
            f"| Links live | {d['links_live_pct']}% |",
            f"| Dates inside the window | {d['dates_in_window_pct']}% |",
            f"| Evidence quotes found in source | {d['quotes_grounded_pct']}% |",
            f"| Claims an independent judge supported | {d.get('claims_supported_pct', 'not run')}% of {d.get('claims_judged', 0)} |",
            f"| Summaries passing verification first time | {d['first_pass_verified_pct']}% |",
            f"| Articles rejected by the verifier | {d['rejected_by_verifier']} |",
            f"| Sessions within 15-20 minutes | {d['reading_in_target_pct']}% {d['reading_minutes']} |",
            f"| Distinct sources used | {d['distinct_sources']} |",
            f"| Repeated articles | {d['repeated_articles']} |",
            f"| Concepts logged | {d['concepts_logged']} |",
            f"| User ratings | {d['user_ratings']} (mean {d.get('user_mean_rating', 'n/a')}, useful {d.get('user_useful_pct', 'n/a')}%) |",
            "",
        ]
    else:
        lines += ["No briefs have been generated yet.", ""]
    p = r["personalization"]
    lines += [f"**Personalization test.** Same {p['pool']} articles, different learner profiles.", "",
              "| Comparison | Shortlist overlap |", "|---|---|"]
    lines += [f"| {k} | {v}% |" for k, v in p["shortlist_overlap_pct"].items()]
    lines += ["", "| Profile | Shortlist matching its top 3 topics |", "|---|---|"]
    lines += [f"| {k} | {v}% |" for k, v in p["shortlist_matches_own_top_topics_pct"].items()]
    lines += ["", "## nextLevelPersonalCoachForCareerLevel", ""]
    if "extraction" in c:
        e, s = c["extraction"], c["calibration"]
        lines += [
            f"**Skill extraction** on {e['posts']} hand-labeled job posts written for this test: precision {e['precision']}, "
            f"recall {e['recall']}, F1 {e['f1']}.", "",
            "**Grading calibration** on seeded, simulated answers:", "",
            "| Question | Strong | Partial | Wrong | Confident bluff | Prompt injection |", "|---|---|---|---|---|---|",
        ]
        lines += [f"| {x['question']}... | {x['strong']} | {x['partial']} | {x['wrong']} | {x['bluff']} | {x['injection']} |"
                  for x in s["scores"]]
        lines += ["",
                  f"- Strong > partial > wrong held for {s['ordering_correct_pct']}% of questions.",
                  f"- The bluff scored below the strong answer on {s['bluff_scored_below_strong_pct']}% of questions.",
                  f"- The highest score a prompt injection earned was {s['injection_max_score']}.",
                  f"- Grading the same answer twice differed by {s['repeat_mean_abs_diff']} points on average.", ""]
    else:
        lines += ["LLM-based checks were not run because no API key was set.", ""]
    lines += [f"**Resource links:** {c['resources']['links_live_pct']}% of {c['resources']['resources']} are live.", ""]
    g = c["progress"]
    lines += [f"**User progress:** {g['real_sessions']} real session(s), {g['answers']} question(s) answered and "
              f"{g['skipped']} skipped. Skipped questions score 0, so they lower the measured scores.", ""]
    if g["real_sessions"] == 1:
        lines += [f"Baseline readiness is {g['readiness_latest']}, with {g['measured_share_latest']}% backed by measured "
                  "answers. A second session is needed to show any change."]
    elif g["real_sessions"] > 1:
        lines += [f"Readiness went from {g['readiness_first']} to {g['readiness_latest']}, "
                  f"with {g['measured_share_latest']}% backed by measured answers."]
    for skill, change in g["skills_retested"].items():
        lines.append(f"- {skill}: {change['first']} to {change['latest']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    store = Store()
    profile = load_profile()
    llm = OpenAILLM(store) if os.getenv("OPENAI_API_KEY") else None
    results = {"date": date.today().isoformat(), "daily": daily_quality(store, llm),
               "personalization": personalization(profile),
               "coach": {"resources": resources_check(), "progress": progress(store)}}
    if llm:
        results["coach"]["extraction"] = skill_extraction(llm)
        results["coach"]["calibration"] = scoring_calibration(llm)
    results["spend"] = store.total_spend()
    (HERE / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    text = to_markdown(results)
    (HERE / "RESULTS.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
