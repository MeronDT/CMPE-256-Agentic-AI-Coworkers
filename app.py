"""Streamlit UI for both agents. Run with: streamlit run app.py"""
from __future__ import annotations

import uuid
from datetime import date, datetime

import pandas as pd
import streamlit as st
from langgraph.types import Command

from coworkers import config
from coworkers.coach.graph import build_graph as build_coach
from coworkers.coach.graph import initial_state, open_checkpointer
from coworkers.coach.render import report_markdown
from coworkers.daily.graph import run_brief
from coworkers.daily.render import brief_markdown
from coworkers.llm import OpenAILLM
from coworkers.memory import Store
from coworkers.profile import load_profile

st.set_page_config(page_title="Agentic AI Coworkers", layout="wide")


@st.cache_resource
def shared():
    return Store(), open_checkpointer()


store, checkpointer = shared()
profile = load_profile()


def get_llm():
    try:
        return OpenAILLM(store)
    except RuntimeError as exc:
        st.error(str(exc))
        st.stop()


def daily_tab() -> None:
    briefs = {b["brief_date"]: b["payload"] for b in store.briefs()}
    left, right = st.columns([1, 3])
    with left:
        if st.button("Generate today's brief", type="primary"):
            with st.spinner("Finding, ranking and verifying articles..."):
                run_brief(get_llm(), store, profile, date.today())
            st.rerun()
        if not briefs:
            st.info("No briefs yet.")
            return
        chosen = st.selectbox("Brief", sorted(briefs, reverse=True))
    brief = briefs[chosen]
    with right:
        st.markdown(brief_markdown(brief), unsafe_allow_html=False)
        st.subheader("Rate today's articles")
        rated = {f["url"]: f["rating"] for f in store.feedback()}
        for item in brief["items"]:
            rating = st.slider(item["title"][:80], 1, 5, rated.get(item["url"], 3), key=f"rate-{chosen}-{item['url']}")
            if st.button("Save rating", key=f"save-{chosen}-{item['url']}"):
                store.add_feedback(item["url"], rating, item["topics"], profile["interests"])
                st.toast("Saved. Future briefs will adjust.")


def coach_tab() -> None:
    st.caption(f"Milestone: {profile['milestone']['title']}")
    session_id = st.session_state.get("session_id")
    if not session_id:
        if st.button("Start a coaching session", type="primary"):
            session_id = f"{datetime.now():%Y%m%d-%H%M}-{uuid.uuid4().hex[:4]}"
            graph = build_coach(get_llm(), store, checkpointer=checkpointer)
            with st.spinner("Finding opportunities and analyzing the market..."):
                graph.invoke(initial_state(session_id, profile, date.today()), _thread(session_id))
            st.session_state.session_id = session_id
            st.rerun()
        return
    graph = build_coach(get_llm(), store, checkpointer=checkpointer)
    state = graph.get_state(_thread(session_id))
    history = state.values.get("history") or []
    if history:
        last = history[-1]
        st.success(f"Last answer: {last['score']}/100")
        st.write(last["evaluation"]["feedback"])
    if state.tasks and state.tasks[0].interrupts:
        question = state.tasks[0].interrupts[0].value
        label = "Follow-up" if question["is_follow_up"] else f"Question {question['number']} of {question['total']}"
        st.subheader(f"{label}: {question['skill']} ({question['kind']})")
        st.markdown(question["prompt"])
        answer = st.text_area("Your answer", height=220, key=f"answer-{len(history)}")
        if st.button("Submit answer", type="primary"):
            with st.spinner("Evaluating..."):
                graph.invoke(Command(resume=answer), _thread(session_id))
            st.rerun()
    elif state.values.get("report"):
        st.markdown(report_markdown(state.values["report"]))
        if st.button("Finish"):
            del st.session_state["session_id"]
            st.rerun()


def _thread(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}, "recursion_limit": 120}


def progress_tab() -> None:
    reports = store.reports()
    a, b, c, d = st.columns(4)
    a.metric("Briefs", len(store.briefs()))
    b.metric("Concepts learned", len(store.concepts()))
    c.metric("Readiness", f"{reports[-1]['readiness']}/100" if reports else "No session yet")
    d.metric("API spend", f"${store.total_spend():.3f} of ${config.BUDGET_USD:.2f}")
    if reports:
        st.subheader("Readiness over time")
        st.line_chart(pd.DataFrame({"date": [r["payload"]["date"] for r in reports],
                                    "readiness": [r["readiness"] for r in reports]}).set_index("date"))
    history = store.skill_history()
    if history:
        st.subheader("Measured skill scores")
        st.dataframe(pd.DataFrame(history)[["created_at", "skill", "score"]], hide_index=True)
    concepts = store.concepts()
    if concepts:
        st.subheader("Concept log")
        st.dataframe(pd.DataFrame(concepts)[["learned_on", "name", "explanation"]], hide_index=True)


st.title("Agentic AI Coworkers")
daily, coach, progress = st.tabs(["DailyTechUpgradeAgent", "nextLevelPersonalCoachForCareerLevel", "Progress"])
with daily:
    daily_tab()
with coach:
    coach_tab()
with progress:
    progress_tab()
