"""Deterministic scoring: answer scores, gap priority and milestone readiness."""
from __future__ import annotations

from .. import config

MET_POINTS = {"yes": 1.0, "partly": 0.5, "no": 0.0}


def answer_score(criteria: list[dict]) -> float:
    """Score from the rubric verdicts, so the number can't drift from the feedback."""
    if not criteria:
        return 0.0
    return round(100 * sum(MET_POINTS[c["met"]] for c in criteria) / len(criteria), 1)


def proficiency(skill: str, measured: dict[str, float], priors: dict[str, float]) -> float:
    """0-1 level. A measured score beats the resume-based estimate."""
    if skill in measured:
        return measured[skill] / 100
    return priors.get(skill, 0.2)


def gap_priorities(demand: dict[str, float], measured: dict[str, float], priors: dict[str, float]) -> list[dict]:
    """Rank skills by how much the market wants them times how far the learner is from ready."""
    rows = []
    for skill, weight in demand.items():
        level = proficiency(skill, measured, priors)
        rows.append({"skill": skill, "demand": weight, "level": round(level, 2),
                     "measured": skill in measured, "priority": round(weight * (1 - level), 3)})
    return sorted(rows, key=lambda r: r["priority"], reverse=True)


def readiness(demand: dict[str, float], measured: dict[str, float], priors: dict[str, float]) -> dict:
    """Demand-weighted readiness, with the share of it backed by measured evidence."""
    total = sum(demand.values())
    if not total:
        return {"score": 0.0, "measured_share": 0.0}
    score = sum(w * proficiency(s, measured, priors) for s, w in demand.items()) / total
    share = sum(w for s, w in demand.items() if s in measured) / total
    return {"score": round(100 * score, 1), "measured_share": round(100 * share, 1)}


def skill_session_scores(answers: list[dict]) -> dict[str, float]:
    """Average each skill's answers, including follow-ups."""
    grouped: dict[str, list[float]] = {}
    for answer in answers:
        grouped.setdefault(answer["skill"], []).append(answer["score"])
    return {skill: round(sum(s) / len(s), 1) for skill, s in grouped.items()}


def boosted_topics(gaps: list[dict], top: int = 3) -> list[str]:
    """Daily-brief topics to raise, from the biggest coaching gaps."""
    topics = []
    for gap in gaps[:top]:
        topic = config.SKILL_TO_TOPIC.get(gap["skill"])
        if topic and topic not in topics:
            topics.append(topic)
    return topics
