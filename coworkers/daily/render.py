"""Render a daily brief to Markdown."""
from __future__ import annotations

from .. import config


def brief_markdown(brief: dict) -> str:
    lines = [f"# Daily Technical Learning Brief: {brief['date']}", ""]
    if brief["is_replay"]:
        lines += ["> **Replay.** Generated later using only articles published on or before this date.", ""]
    lines += [
        f"**Reading session:** about {brief['total_minutes']} minutes. "
        f"**Concepts logged so far:** {brief.get('concepts_total', 0)}.",
        f"Chosen from {brief['fresh_candidates']} new articles in the last {config.WINDOW_DAYS} days.", "",
    ]
    if brief["items"]:
        lines += ["## Today's new concepts", ""]
        lines += [f"- **{i['new_concept_name']}:** {i['new_concept_explanation']}" for i in brief["items"]]
        lines.append("")
    for number, item in enumerate(brief["items"], 1):
        lines += [
            f"## {number}. {item['title']}", "",
            f"**Source:** {item['source']} | **Published:** {item['published']} | **Read:** {item['minutes']} min",
            f"**URL:** {item['url']}", "",
            item["summary"], "",
            "**Key insights**", "",
        ]
        for insight in item["insights"]:
            lines.append(f"- {insight['point']} *(\"{insight['evidence_quote']}\")*")
        lines += [
            "",
            f"**Takeaway:** {item['takeaway']}", "",
            f"**Adds to your knowledge:** {item['knowledge_contribution']}", "",
            f"**Helps your career goal:** {item['career_contribution']}", "",
            f"**Where to focus:** {item['read_focus']}", "",
        ]
        if item["kind"] == "abstract":
            lines += ["*Summarized from the abstract only, because the full text was not available.*", ""]
    if brief["items"]:
        lines += ["## Recall check", "", "Answer these from memory after reading.", ""]
        lines += [f"{n}. {i['recall_question']}" for n, i in enumerate(brief["items"], 1)]
        lines += ["", "<details><summary>Answers</summary>", ""]
        lines += [f"{n}. {i['recall_answer']}" for n, i in enumerate(brief["items"], 1)]
        lines += ["", "</details>", "", "## References", ""]
        lines += [f"{n}. {i['title']}. {i['source']}, {i['published']}. {i['url']}" for n, i in enumerate(brief["items"], 1)]
    if brief["warnings"]:
        lines += ["", "## Run notes", ""] + [f"- {w}" for w in brief["warnings"]]
    return "\n".join(lines) + "\n"


def render_brief(brief: dict) -> str:
    folder = config.SAMPLES_DIR / "briefs"
    folder.mkdir(parents=True, exist_ok=True)
    text = brief_markdown(brief)
    (folder / f"{brief['date']}.md").write_text(text, encoding="utf-8")
    return text
