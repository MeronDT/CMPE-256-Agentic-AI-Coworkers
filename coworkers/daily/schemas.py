"""Structured LLM outputs for the daily agent."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ArticleScore(BaseModel):
    index: int
    relevance: int = Field(description="1-10 fit with the learner's interests and milestone")
    technical_depth: int = Field(description="1-10; product announcements and marketing score below 5")
    reason: str


class RankOut(BaseModel):
    scores: list[ArticleScore]


class Insight(BaseModel):
    point: str
    evidence_quote: str = Field(description="Copied word for word from the article, 5-30 words")


class SummaryOut(BaseModel):
    summary: str = Field(description="3-4 sentences")
    insights: list[Insight] = Field(description="Exactly 3 technical insights")
    takeaway: str = Field(description="One thing the learner can apply")
    knowledge_contribution: str = Field(description="What this adds to the learner's technical knowledge")
    career_contribution: str = Field(description="How this helps the learner's career milestone")
    read_focus: str = Field(description="Which sections to read closely in the time available")
    new_concept_name: str = Field(description="One concept that is new to the learner, 1-5 words")
    new_concept_explanation: str = Field(description="Two sentences a CS graduate can follow")
    recall_question: str
    recall_answer: str
