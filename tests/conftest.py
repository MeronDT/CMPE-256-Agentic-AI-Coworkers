"""A scripted LLM lets both graphs run end to end without an API key."""
from __future__ import annotations

import pytest

from coworkers import config
from coworkers.coach import schemas as cs
from coworkers.daily import schemas as ds
from coworkers.memory import Store


class StubLLM:
    def __init__(self):
        self.calls = []
        self.bad_quotes_for = 0

    def parse(self, schema, prompt, *, system, purpose, model=None, max_tokens=2000):
        self.calls.append(purpose)
        if schema is ds.RankOut:
            count = prompt.count("\n[") + (1 if "<untrusted>\n[0]" in prompt else 0)
            scores = [ds.ArticleScore(index=i, relevance=9 - i % 5, technical_depth=8, reason="fits") for i in range(count + 1)]
            return ds.RankOut(scores=scores)
        if schema is ds.SummaryOut:
            body = prompt.split("<untrusted>\n")[1]
            words = body.split()
            quote = " ".join(words[5:13])
            if self.bad_quotes_for > 0:
                self.bad_quotes_for -= 1
                quote = "this sentence never appears anywhere in the source"
            name = f"concept {len(self.calls)}"
            return ds.SummaryOut(summary="s", insights=[ds.Insight(point="p", evidence_quote=quote)] * 3, takeaway="t",
                                 knowledge_contribution="k", career_contribution="c", read_focus="f",
                                 new_concept_name=name, new_concept_explanation="e", recall_question="q", recall_answer="a")
        if schema is cs.MarketAnalysis:
            return cs.MarketAnalysis(skills=[cs.SkillDemand(skill="system-design", weight=5, evidence="e"),
                                             cs.SkillDemand(skill="databases-sql", weight=4, evidence="e"),
                                             cs.SkillDemand(skill="python", weight=3, evidence="e")], themes=["scale"])
        if schema is cs.QuestionSet:
            return cs.QuestionSet(questions=[
                cs.Question(skill=s, kind="concept", difficulty=3, prompt=f"Explain {s}", rubric=["a", "b"], why_this_question="gap")
                for s in ("system-design", "databases-sql", "python", "system-design")])
        if schema is cs.AnswerEvaluation:
            follow = "Go deeper?" if "Go deeper" not in prompt else None
            return cs.AnswerEvaluation(
                criteria=[cs.CriterionResult(criterion="a", met="yes", comment="c"),
                          cs.CriterionResult(criterion="b", met="partly", comment="c")],
                strengths=["clear"], gaps=["depth"], feedback="f", model_outline="m",
                follow_up=follow, follow_up_rubric=["x"] if follow else [])
        if schema is cs.Recommendations:
            return cs.Recommendations(strengths=["s"], knowledge_gaps=["g"],
                                      actions=[cs.PlanAction(action="do", skill="dsa", due_in_days=7, measure="m")],
                                      resource_ids=[0, 999], research_angle="r", venture_angle="v", milestone_status="close")
        raise AssertionError(schema)


@pytest.fixture
def stub():
    return StubLLM()


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SAMPLES_DIR", tmp_path / "samples")
    return Store(":memory:")


@pytest.fixture
def profile():
    from coworkers.profile import load_profile
    return load_profile()
