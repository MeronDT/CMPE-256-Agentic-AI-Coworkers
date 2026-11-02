"""nextLevelPersonalCoachForCareerLevel: a LangGraph coaching session that pauses for each answer."""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import TypedDict

import yaml
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .. import config
from ..llm import LLMClient, wrap_untrusted
from ..memory import Store
from . import assess, opportunities
from .render import render_report
from .schemas import AnswerEvaluation, JobSkills, MarketAnalysis, QuestionSet, Recommendations

ANALYZE_SYSTEM = (
    "You analyze hiring demand for a software engineering candidate. Read the job posts, blogs and papers and "
    "report which skills from the allowed taxonomy matter most, weighted by how often and how strongly they appear."
)
QUESTION_SYSTEM = (
    "You are a rigorous software engineering interviewer. Write questions aimed at the candidate's listed gaps, "
    "at internship level and above. Where possible connect a question to the candidate's real projects. "
    "Use a mix of kinds: at least one coding exercise and one system design or scenario question. Coding "
    "questions must be solvable in plain text in under 10 minutes. Each rubric item must be specific enough "
    "for two graders to agree."
)
EVAL_SYSTEM = (
    "You evaluate an interview answer strictly against the rubric. Mark each criterion yes, partly or no using "
    "only what the answer says. Do not give credit for what the candidate probably knows. Length and confidence "
    "are not evidence. Coaching should be direct and specific. Do not reveal the answer inside follow_up."
)
PLAN_SYSTEM = (
    "You are a career coach. Base every statement on the supplied assessment. Do not flatter. Recommend resources "
    "only by index from the supplied list. Be honest about how much evidence the assessment rests on."
)


class State(TypedDict, total=False):
    session_id: str
    today: str
    simulated: bool
    profile: dict
    opportunities: dict
    warnings: list
    market: dict
    demand: dict
    job_skills: list
    gaps: list
    questions: list
    q_index: int
    follow_ups: int
    current: dict
    history: list
    report: dict


def load_resources() -> list[dict]:
    path = Path(__file__).with_name("resources.yaml")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def evaluate_answer(llm: LLMClient, question: str, rubric: list[str], answer: str) -> dict:
    """Grade one answer. Also used by the evaluation harness."""
    if not answer.strip() or answer.strip().lower() in {"skip", "idk", "i don't know", "pass"}:
        criteria = [{"criterion": r, "met": "no", "comment": "Not answered."} for r in rubric]
        return {"criteria": criteria, "strengths": [], "gaps": ["No answer given."],
                "feedback": "Skipped, so this counts as a gap. Study the outline, then try it again.",
                "model_outline": "", "follow_up": None, "follow_up_rubric": [], "score": 0.0}
    rubric_text = "\n".join(f"- {r}" for r in rubric)
    prompt = f"Question:\n{question}\n\nRubric:\n{rubric_text}\n\nCandidate answer:\n{wrap_untrusted(answer)}"
    out = llm.parse(AnswerEvaluation, prompt, system=EVAL_SYSTEM, purpose="coach.evaluate",
                    model=config.EVAL_MODEL, max_tokens=1500).model_dump()
    out["score"] = assess.answer_score(out["criteria"])
    return out


def build_graph(llm: LLMClient, store: Store, *, scout: Callable = opportunities.scout, checkpointer=None):
    def load_context(state: State) -> dict:
        return {"warnings": [], "history": [], "q_index": 0, "follow_ups": 0}

    def scout_node(state: State) -> dict:
        found, warnings = scout(state["profile"])
        grouped = opportunities.top_by_kind(found)
        store.save_opportunities([i for group in grouped.values() for i in group], state["today"])
        return {"opportunities": grouped, "warnings": state["warnings"] + warnings}

    def analyze(state: State) -> dict:
        grouped = state["opportunities"]
        postings = [i for i in grouped["internship"] + grouped["job"] if i["text"]][:6]
        if len(postings) < 3:
            postings = [i for i in grouped["internship"] + grouped["job"]][:6]
        read = [b["payload"]["items"] for b in store.briefs()[-3:]]
        blogs = [f"{i['title']}: {i['summary']}" for items in read for i in items][:6]
        papers = [f"{i['title']}: {i['text'][:500]}" for i in grouped["research"]]
        material = "\n\n".join(
            [f"JOB POST: {p['title']} at {p['org']}\n{(p['text'] or 'Title only.')[:1800]}" for p in postings]
            + [f"BLOG: {b}" for b in blogs] + [f"PAPER: {p}" for p in papers])
        out = llm.parse(MarketAnalysis, f"Target: {state['profile']['milestone']['title']}.\n\n{wrap_untrusted(material)}",
                        system=ANALYZE_SYSTEM, purpose="coach.analyze", max_tokens=1200)
        demand: dict[str, float] = {}
        for row in out.skills:
            demand[row.skill] = max(demand.get(row.skill, 0), max(1, min(5, row.weight)))
        return {"market": out.model_dump(), "demand": demand,
                "job_skills": [{"title": p["title"], "org": p["org"]} for p in postings]}

    def assess_gaps(state: State) -> dict:
        gaps = assess.gap_priorities(state["demand"], store.latest_skill_scores(), state["profile"]["skills"])
        return {"gaps": gaps}

    def generate_questions(state: State) -> dict:
        profile = state["profile"]
        past = [a["question"] for a in store.answers()][-15:]
        gap_text = "\n".join(f"- {g['skill']} (demand {g['demand']}, level {g['level']})" for g in state["gaps"][:6])
        prompt = (f"Candidate: {profile['degree']}.\nMilestone: {profile['milestone']['title']}.\n"
                  "Projects:\n" + "\n".join(f"- {p}" for p in profile["projects"]) +
                  f"\n\nBiggest gaps:\n{gap_text}\n\nMarket themes: {', '.join(state['market']['themes'])}\n\n"
                  f"Avoid repeating: {past or 'nothing yet'}\n\n"
                  f"Write exactly {config.QUESTIONS_PER_SESSION} questions, one per gap, biggest gap first.")
        out = llm.parse(QuestionSet, prompt, system=QUESTION_SYSTEM, purpose="coach.questions",
                        model=config.EVAL_MODEL, max_tokens=2500)
        questions = [q.model_dump() for q in out.questions[:config.QUESTIONS_PER_SESSION]]
        return {"questions": questions, "current": _as_current(questions[0], 0)}

    def ask(state: State) -> dict:
        current = state["current"]
        answer = interrupt({"number": current["number"], "total": len(state["questions"]), "skill": current["skill"],
                            "kind": current["kind"], "prompt": current["prompt"], "is_follow_up": current["is_follow_up"],
                            "why": current.get("why_this_question", "")})
        return {"current": {**current, "answer": answer}}

    def evaluate(state: State) -> dict:
        current = state["current"]
        result = evaluate_answer(llm, current["prompt"], current["rubric"], current["answer"])
        store.save_answer(state["session_id"], current["skill"], current["kind"], current["prompt"], current["answer"],
                          result["score"], result, state["simulated"])
        record = {**current, "evaluation": result, "score": result["score"]}
        return {"history": state["history"] + [record], "current": record}

    def next_step(state: State) -> dict:
        evaluation = state["current"]["evaluation"]
        if evaluation["follow_up"] and evaluation["follow_up_rubric"] and state["follow_ups"] < config.MAX_FOLLOW_UPS:
            base = state["current"]
            return {"follow_ups": state["follow_ups"] + 1,
                    "current": {"number": base["number"], "skill": base["skill"], "kind": base["kind"],
                                "prompt": evaluation["follow_up"], "rubric": evaluation["follow_up_rubric"],
                                "is_follow_up": True}}
        index = state["q_index"] + 1
        if index < len(state["questions"]):
            return {"q_index": index, "follow_ups": 0, "current": _as_current(state["questions"][index], index)}
        return {"q_index": index, "current": {}}

    def route(state: State) -> str:
        return "ask" if state["current"] else "report"

    def report(state: State) -> dict:
        profile = state["profile"]
        session_scores = assess.skill_session_scores(state["history"])
        for skill, score in session_scores.items():
            store.save_skill_score(state["session_id"], skill, score, state["simulated"])
        measured = {**store.latest_skill_scores(), **session_scores}
        gaps = assess.gap_priorities(state["demand"], measured, profile["skills"])
        ready = assess.readiness(state["demand"], measured, profile["skills"])
        previous = store.reports()
        catalog = load_resources()
        for brief in store.briefs()[-5:]:
            catalog += [{"title": i["title"], "url": i["url"], "skills": ["recent brief"]} for i in brief["payload"]["items"]]
        listing = "\n".join(f"[{i}] {r['title']} ({', '.join(r['skills'])})" for i, r in enumerate(catalog))
        transcript = "\n".join(
            f"- {h['skill']} ({h['kind']}{', follow-up' if h['is_follow_up'] else ''}): score {h['score']}. "
            f"Gaps: {'; '.join(h['evaluation']['gaps'])}. Strengths: {'; '.join(h['evaluation']['strengths'])}"
            for h in state["history"])
        leads = "\n".join(f"- {i['kind']}: {i['title']}" for i in state["opportunities"]["research"] + state["opportunities"]["venture"])
        prompt = (f"Milestone: {profile['milestone']['title']}. Readiness: {ready['score']}/100, with "
                  f"{ready['measured_share']}% of it backed by measured answers.\nVenture interests: "
                  f"{', '.join(profile['venture_interests'])}\n\nAssessment:\n{transcript}\n\nRanked gaps:\n"
                  + "\n".join(f"- {g['skill']}: priority {g['priority']}" for g in gaps[:6])
                  + f"\n\nResearch and venture leads:\n{leads}\n\nResources:\n{listing}")
        plan = llm.parse(Recommendations, prompt, system=PLAN_SYSTEM, purpose="coach.plan",
                         model=config.EVAL_MODEL, max_tokens=1800).model_dump()
        resources = [catalog[i] for i in plan["resource_ids"] if 0 <= i < len(catalog)]
        boosted = assess.boosted_topics(gaps)
        weights = store.topic_weights(profile["interests"])
        if not state["simulated"]:
            for topic in boosted:
                store.set_topic_weight(topic, weights.get(topic, 1.0) + 0.2)
        report_data = {
            "session_id": state["session_id"], "date": state["today"], "simulated": state["simulated"],
            "milestone": profile["milestone"]["title"], "readiness": ready, "previous_readiness":
            [{"date": r["payload"]["date"], "score": r["readiness"]} for r in previous],
            "opportunities": {k: [{f: i.get(f, "") for f in ("title", "org", "url", "location", "posted", "fit", "notes")}
                                  for i in v] for k, v in state["opportunities"].items()},
            "market": state["market"], "job_skills": state["job_skills"], "gaps": gaps, "session_scores": session_scores,
            "history": state["history"], "plan": plan, "resources": resources, "boosted_topics": boosted,
            "warnings": state["warnings"],
        }
        store.save_report(state["session_id"], ready["score"], report_data, state["simulated"])
        render_report(report_data)
        return {"report": report_data}

    graph = StateGraph(State)
    for name, fn in [("load_context", load_context), ("scout", scout_node), ("analyze", analyze),
                     ("assess_gaps", assess_gaps), ("generate_questions", generate_questions), ("ask", ask),
                     ("evaluate", evaluate), ("next_step", next_step), ("report", report)]:
        graph.add_node(name, fn)
    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "scout")
    graph.add_edge("scout", "analyze")
    graph.add_edge("analyze", "assess_gaps")
    graph.add_edge("assess_gaps", "generate_questions")
    graph.add_edge("generate_questions", "ask")
    graph.add_edge("ask", "evaluate")
    graph.add_edge("evaluate", "next_step")
    graph.add_conditional_edges("next_step", route, {"ask": "ask", "report": "report"})
    graph.add_edge("report", END)
    return graph.compile(checkpointer=checkpointer)


def _as_current(question: dict, index: int) -> dict:
    return {**question, "number": index + 1, "is_follow_up": False}


def open_checkpointer() -> SqliteSaver:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(config.CHECKPOINT_PATH, check_same_thread=False))


def initial_state(session_id: str, profile: dict, today: date, simulated: bool = False) -> dict:
    return {"session_id": session_id, "today": today.isoformat(), "simulated": simulated, "profile": profile}
