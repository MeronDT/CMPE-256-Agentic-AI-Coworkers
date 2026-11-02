"""Run a labeled demonstration session where an LLM plays the candidate.

It is flagged simulated, so it never changes real skill scores, readiness or topic weights.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coworkers.coach.graph import build_graph, initial_state  # noqa: E402
from coworkers.llm import OpenAILLM  # noqa: E402
from coworkers.memory import Store  # noqa: E402
from coworkers.profile import load_profile  # noqa: E402

CANDIDATE_SYSTEM = (
    "Role-play a first-year master's student applying for software engineering internships. You have solid "
    "fundamentals but limited production experience. Answer in 3-6 sentences of plain text. Get the main idea "
    "right, and leave one realistic gap or small mistake without pointing it out."
)


class CandidateAnswer(BaseModel):
    answer: str


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    store = Store()
    llm = OpenAILLM(store)
    session_id = f"demo-{date.today():%Y%m%d}"
    graph = build_graph(llm, store, checkpointer=MemorySaver())
    thread = {"configurable": {"thread_id": session_id}, "recursion_limit": 120}
    result = graph.invoke(initial_state(session_id, load_profile(), date.today(), simulated=True), thread)
    while result.get("__interrupt__"):
        question = result["__interrupt__"][0].value
        answer = llm.parse(CandidateAnswer, question["prompt"], system=CANDIDATE_SYSTEM,
                           purpose="eval.simulated_candidate", max_tokens=500).answer
        result = graph.invoke(Command(resume=answer), thread)
    report = result["report"]
    print(f"Simulated readiness {report['readiness']['score']}, answers {len(report['history'])}")
    print([(h["skill"], h["is_follow_up"], h["score"]) for h in report["history"]])


if __name__ == "__main__":
    main()
