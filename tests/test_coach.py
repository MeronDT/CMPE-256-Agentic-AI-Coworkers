from datetime import date

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from coworkers.coach import assess
from coworkers.coach.graph import build_graph, evaluate_answer, initial_state
from coworkers.coach.opportunities import _classify, fit_score, top_by_kind, SKILL_TERMS
from coworkers.llm import BudgetExceeded, OpenAILLM, cost_of


def fake_scout(profile):
    items = [
        {"id": str(i), "kind": kind, "title": f"{kind} {i}", "org": "Org", "url": f"https://x.com/{kind}{i}",
         "location": "San Jose, CA", "posted": "2026-10-30", "text": "We use Python, SQL and distributed systems.",
         "notes": "", "fit": 0.8}
        for i, kind in enumerate(["internship", "internship", "job", "research", "venture"])
    ]
    return items, ["Lever/spotify was unavailable"]


def run_session(stub, store, profile, simulated=False, answer="My careful answer"):
    graph = build_graph(stub, store, scout=fake_scout, checkpointer=MemorySaver())
    thread = {"configurable": {"thread_id": "s1"}, "recursion_limit": 120}
    result = graph.invoke(initial_state("s1", profile, date(2026, 11, 1), simulated=simulated), thread)
    asked = []
    while result.get("__interrupt__"):
        asked.append(result["__interrupt__"][0].value)
        result = graph.invoke(Command(resume=answer), thread)
    return result["report"], asked


def test_session_pauses_for_every_answer_and_writes_a_report(stub, store, profile):
    report, asked = run_session(stub, store, profile)
    assert sum(not q["is_follow_up"] for q in asked) == 4
    assert any(q["is_follow_up"] for q in asked)
    assert len(store.answers("s1")) == len(asked)
    assert report["readiness"]["score"] > 0
    assert report["opportunities"]["internship"]
    assert report["opportunities"]["venture"]
    assert "Lever/spotify was unavailable" in report["warnings"]


def test_follow_ups_are_capped(stub, store, profile):
    from coworkers import config
    report, asked = run_session(stub, store, profile)
    runs, count = [], 0
    for q in asked:
        count = count + 1 if q["is_follow_up"] else 0
        runs.append(count)
    assert max(runs) <= config.MAX_FOLLOW_UPS


def test_resources_cannot_be_invented(stub, store, profile):
    report, _ = run_session(stub, store, profile)
    assert len(report["resources"]) == 1  # index 999 from the model was discarded


def test_report_gaps_raise_daily_topics(stub, store, profile):
    before = store.topic_weights(profile["interests"])
    report, _ = run_session(stub, store, profile)
    after = store.topic_weights(profile["interests"])
    assert report["boosted_topics"]
    assert any(after[t] > before[t] for t in report["boosted_topics"])


def test_simulated_sessions_never_touch_real_progress(stub, store, profile):
    before = store.topic_weights(profile["interests"])
    run_session(stub, store, profile, simulated=True)
    assert store.latest_skill_scores() == {}
    assert store.reports() == []
    assert store.topic_weights(profile["interests"]) == before


def test_second_session_is_compared_with_the_first(stub, store, profile):
    run_session(stub, store, profile)
    graph = build_graph(stub, store, scout=fake_scout, checkpointer=MemorySaver())
    thread = {"configurable": {"thread_id": "s2"}, "recursion_limit": 120}
    result = graph.invoke(initial_state("s2", profile, date(2026, 11, 2)), thread)
    while result.get("__interrupt__"):
        result = graph.invoke(Command(resume="again"), thread)
    assert len(result["report"]["previous_readiness"]) == 1


def test_blank_answer_scores_zero_without_an_llm_call(stub):
    result = evaluate_answer(stub, "Q", ["a", "b"], "   ")
    assert result["score"] == 0.0
    assert stub.calls == []


def test_answer_score_comes_from_the_rubric():
    assert assess.answer_score([{"met": "yes"}, {"met": "partly"}, {"met": "no"}, {"met": "yes"}]) == 62.5


def test_measured_score_beats_resume_estimate():
    gaps = assess.gap_priorities({"dsa": 5, "python": 1}, {"dsa": 90}, {"dsa": 0.1, "python": 0.1})
    assert gaps[0]["skill"] == "python" or gaps[0]["priority"] < 1
    assert next(g for g in gaps if g["skill"] == "dsa")["measured"]


def test_readiness_reports_how_much_is_measured():
    ready = assess.readiness({"dsa": 3, "python": 1}, {"dsa": 80}, {"python": 0.4})
    assert ready == {"score": 70.0, "measured_share": 75.0}


@pytest.mark.parametrize("title,expected", [
    ("Software Engineer Intern", "internship"), ("Backend Engineering Internship", "internship"),
    ("Software Engineer, New Grad", "job"), ("Senior Software Engineer", None),
    ("Marketing Intern", None), ("Staff Platform Engineer", None), ("Software Engineer", None),
    ("High School Internship, Software Engineering", None), ("Software Engineer Intern (Winter 2027)", None),
])
def test_role_classification(title, expected):
    assert _classify(title) == expected


def test_location_match_needs_a_whole_word(profile):
    base = {"kind": "internship", "title": "Software Engineer Intern", "text": ""}
    assert fit_score({**base, "location": "San Jose, CA"}, profile, SKILL_TERMS) > \
        fit_score({**base, "location": "Cambridge, UK"}, profile, SKILL_TERMS)
    assert fit_score({**base, "location": "Oakland, CA"}, profile, SKILL_TERMS) > \
        fit_score({**base, "location": "Toronto, Canada"}, profile, SKILL_TERMS)


def test_skill_terms_do_not_match_inside_words(profile):
    item = {"kind": "research", "title": "t", "location": "", "text": "an interesting and rapid result"}
    assert fit_score(item, profile, SKILL_TERMS) == fit_score({**item, "text": "nothing relevant"}, profile, SKILL_TERMS)


def test_fit_prefers_a_matching_local_role(profile):
    good = {"kind": "internship", "title": "Backend Software Engineer Intern", "location": "San Jose, CA", "text": "python aws"}
    bad = {"kind": "internship", "title": "Firmware Intern", "location": "Berlin", "text": "verilog"}
    assert fit_score(good, profile, SKILL_TERMS) > fit_score(bad, profile, SKILL_TERMS)


def test_top_by_kind_limits_each_group():
    items = [{"kind": "venture", "fit": 1} for _ in range(10)]
    assert len(top_by_kind(items)["venture"]) == 3


def test_budget_cap_stops_calls_before_they_are_made(store, monkeypatch):
    from coworkers import config
    monkeypatch.setattr(config, "BUDGET_USD", 0.01)
    store.record_usage("gpt-5.4-mini", 1, 1, 0.02, "test")

    class NoCalls:
        def __getattr__(self, name):
            raise AssertionError("no API call should happen")

    with pytest.raises(BudgetExceeded):
        OpenAILLM(store, client=NoCalls()).parse(object, "p", system="s", purpose="x")


def test_cost_calculation():
    assert cost_of("gpt-5.4-nano", 1_000_000, 1_000_000) == pytest.approx(1.45)
