"""Structured LLM outputs for the career coach."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Skill = Literal["dsa", "system-design", "concurrency", "databases-sql", "distributed-systems", "cloud-aws",
                "networking", "os-internals", "api-design", "testing-ci", "python", "cpp", "java",
                "javascript-react", "ai-engineering", "behavioral"]


class SkillDemand(BaseModel):
    skill: Skill
    weight: int = Field(description="1-5 importance across the material")
    evidence: str = Field(description="Short phrase from the material showing the demand")


class MarketAnalysis(BaseModel):
    skills: list[SkillDemand]
    themes: list[str] = Field(description="2-4 themes across job posts, blogs and papers")


class JobSkills(BaseModel):
    skills: list[Skill]


class Question(BaseModel):
    skill: Skill
    kind: Literal["concept", "coding", "system_design", "scenario", "behavioral"]
    difficulty: int = Field(description="1-5")
    prompt: str
    rubric: list[str] = Field(description="3-5 specific criteria a good answer meets")
    why_this_question: str


class QuestionSet(BaseModel):
    questions: list[Question]


class CriterionResult(BaseModel):
    criterion: str
    met: Literal["yes", "partly", "no"]
    comment: str


class AnswerEvaluation(BaseModel):
    criteria: list[CriterionResult]
    strengths: list[str]
    gaps: list[str]
    feedback: str = Field(description="Direct and specific coaching, 2-4 sentences")
    model_outline: str = Field(description="What a strong answer would have covered")
    follow_up: str | None = Field(description="A probing question on the weakest point, or a harder extension if the "
                                              "answer was strong. Null if nothing useful remains.")
    follow_up_rubric: list[str] = Field(description="3 criteria for the follow-up. Empty if follow_up is null.")


class PlanAction(BaseModel):
    action: str
    skill: Skill
    due_in_days: int
    measure: str = Field(description="How the learner can tell it is done")


class Recommendations(BaseModel):
    strengths: list[str]
    knowledge_gaps: list[str]
    actions: list[PlanAction] = Field(description="3-6 concrete actions")
    resource_ids: list[int] = Field(description="Indexes from the supplied resource list only")
    research_angle: str = Field(description="One research direction tied to a listed research lead")
    venture_angle: str = Field(description="One small venture idea tied to the learner's interests and a listed signal")
    milestone_status: str = Field(description="Honest two-sentence view of how close the learner is to the milestone")
