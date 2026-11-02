"""Command line for both agents. Run `python -m coworkers --help`."""
from __future__ import annotations

import argparse
import sys
import uuid
from datetime import date, datetime, timedelta

from langgraph.types import Command
from pydantic import BaseModel

from . import config
from .coach.graph import build_graph as build_coach
from .coach.graph import initial_state, open_checkpointer
from .coach.opportunities import scout, top_by_kind
from .daily.graph import run_brief
from .daily.render import brief_markdown
from .llm import OpenAILLM
from .memory import Store
from .profile import load_profile


def read_answer() -> str:
    print("Your answer. Finish with a line containing only END. Type skip to pass.")
    lines = []
    for line in sys.stdin:
        if line.strip() == "END":
            break
        lines.append(line.rstrip("\n"))
        if len(lines) == 1 and line.strip().lower() == "skip":
            break
    return "\n".join(lines)


def show_question(q: dict) -> None:
    label = "Follow-up" if q["is_follow_up"] else f"Question {q['number']} of {q['total']}"
    print(f"\n--- {label} [{q['skill']}, {q['kind']}] ---\n{q['prompt']}\n")


def show_feedback(state: dict) -> None:
    history = state.get("history") or []
    if history:
        last = history[-1]
        print(f"\nScore: {last['score']}/100\n{last['evaluation']['feedback']}")


def cmd_daily(args) -> None:
    store = Store()
    as_of = date.fromisoformat(args.date) if args.date else date.today()
    brief = run_brief(OpenAILLM(store), store, load_profile(), as_of, is_replay=as_of < date.today())
    print(brief_markdown(brief))


def cmd_replay(args) -> None:
    store = Store()
    llm, profile = OpenAILLM(store), load_profile()
    today = date.today()
    done = {b["brief_date"] for b in store.briefs()}
    for offset in range(args.days, 0, -1):
        day = today - timedelta(days=offset)
        if day.isoformat() in done:
            print(f"{day}: already generated")
            continue
        brief = run_brief(llm, store, profile, day, is_replay=True)
        print(f"{day}: {len(brief['items'])} articles, {brief['total_minutes']} min")
    print(f"Spent so far: ${store.total_spend():.4f}")


def cmd_rate(args) -> None:
    store = Store()
    profile = load_profile()
    brief = next((b["payload"] for b in reversed(store.briefs()) if not args.date or b["brief_date"] == args.date), None)
    if brief is None:
        sys.exit("No brief found.")
    for item in brief["items"]:
        rating = input(f"Rate 1-5, blank to skip: {item['title']}\n> ").strip()
        if rating in {"1", "2", "3", "4", "5"}:
            store.add_feedback(item["url"], int(rating), item["topics"], profile["interests"])


def cmd_coach(args) -> None:
    store = Store()
    session_id = args.resume or f"{datetime.now():%Y%m%d-%H%M}-{uuid.uuid4().hex[:4]}"
    graph = build_coach(OpenAILLM(store), store, checkpointer=open_checkpointer())
    thread = {"configurable": {"thread_id": session_id}, "recursion_limit": 120}
    print(f"Session {session_id}. If you stop, resume with: python -m coworkers coach --resume {session_id}")
    if args.resume:
        pending = graph.get_state(thread).tasks
        if not pending:
            sys.exit("That session has nothing left to resume.")
        result = {"__interrupt__": pending[0].interrupts}
    else:
        print("Finding opportunities and analyzing the market...")
        result = graph.invoke(initial_state(session_id, load_profile(), date.today()), thread)
    while result.get("__interrupt__"):
        show_question(result["__interrupt__"][0].value)
        result = graph.invoke(Command(resume=read_answer()), thread)
        show_feedback(result)
    report = result["report"]
    print(f"\nReadiness: {report['readiness']['score']}/100. Report saved in {config.SAMPLES_DIR / 'coaching'}")


def cmd_opportunities(args) -> None:
    found, warnings = scout(load_profile())
    for kind, items in top_by_kind(found).items():
        print(f"\n{kind.upper()}")
        for item in items:
            print(f"  {item['fit']:.2f} {item['title'][:60]} | {item['org']} | {item['location'][:30]} | {item['url']}")
    for warning in warnings:
        print("note:", warning)


class Ping(BaseModel):
    ok: bool


def cmd_check(args) -> None:
    """Confirm the key, models and structured output work. Costs a fraction of a cent."""
    store = Store()
    llm = OpenAILLM(store)
    available = {m.id for m in llm.client.models.list()}
    for model in (config.ROUTINE_MODEL, config.EVAL_MODEL):
        if model not in available:
            close = sorted(m for m in available if "mini" in m or "nano" in m)
            sys.exit(f"{model} is not available to this key. Set it in .env. Options: {close[:12]}")
        reply = llm.parse(Ping, "Set ok to true.", system="Reply in the requested format.", purpose="check", model=model)
        print(f"{model}: ok={reply.ok}")
    print(f"Key works. Spent ${store.total_spend():.4f} of the ${config.BUDGET_USD:.2f} cap.")


def cmd_status(args) -> None:
    store = Store()
    print(f"Briefs: {len(store.briefs())}  Concepts learned: {len(store.concepts())}  "
          f"Coaching reports: {len(store.reports())}")
    print(f"Spent ${store.total_spend():.4f} of the ${config.BUDGET_USD:.2f} cap")
    for row in store.usage_by_purpose():
        print(f"  {row['purpose']}: {row['calls']} calls, ${row['cost']:.4f}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="coworkers")
    sub = parser.add_subparsers(dest="command", required=True)
    daily = sub.add_parser("daily", help="Generate today's brief, or a past date's with --date")
    daily.add_argument("--date")
    daily.set_defaults(fn=cmd_daily)
    replay = sub.add_parser("replay", help="Replay past days from real dated articles")
    replay.add_argument("--days", type=int, default=5)
    replay.set_defaults(fn=cmd_replay)
    rate = sub.add_parser("rate", help="Rate a brief to personalize future ones")
    rate.add_argument("--date")
    rate.set_defaults(fn=cmd_rate)
    coach = sub.add_parser("coach", help="Start or resume a coaching session")
    coach.add_argument("--resume")
    coach.set_defaults(fn=cmd_coach)
    sub.add_parser("opportunities", help="List matched opportunities without using the LLM").set_defaults(fn=cmd_opportunities)
    sub.add_parser("status", help="Show progress and spending").set_defaults(fn=cmd_status)
    sub.add_parser("check", help="Test the API key and models").set_defaults(fn=cmd_check)
    sys.stdout.reconfigure(encoding="utf-8")
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
