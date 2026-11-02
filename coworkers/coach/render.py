"""Render the Personalized Career Readiness Report to Markdown."""
from __future__ import annotations

from .. import config

KIND_TITLES = {"internship": "Internships", "job": "Entry-level jobs", "research": "Research leads",
               "venture": "Entrepreneurial signals"}


def _cell(text) -> str:
    return str(text).replace("|", "/").replace("\n", " ")[:90]


def report_markdown(data: dict) -> str:
    ready = data["readiness"]
    plan = data["plan"]
    lines = [f"# Personalized Career Readiness Report: {data['date']}", ""]
    if data["simulated"]:
        lines += ["> **Simulated session.** The answers below were written to test the coach, not by the learner.", ""]
    lines += [
        f"**Milestone:** {data['milestone']}", "",
        f"**Readiness:** {ready['score']}/100. {ready['measured_share']}% of that weight comes from answers measured "
        "in coaching sessions. The rest is estimated from the resume.", "",
        plan["milestone_status"], "",
    ]
    if data["previous_readiness"]:
        trail = ", ".join(f"{p['date']}: {p['score']}" for p in data["previous_readiness"])
        lines += [f"**Earlier readiness scores:** {trail}", ""]
    lines += ["## Technical assessment", "", "| Skill | Type | Follow-up | Score |", "|---|---|---|---|"]
    lines += [f"| {h['skill']} | {h['kind']} | {'yes' if h['is_follow_up'] else 'no'} | {h['score']} |" for h in data["history"]]
    lines += ["", "## Strengths", ""] + [f"- {s}" for s in plan["strengths"]]
    lines += ["", "## Knowledge gaps", ""] + [f"- {g}" for g in plan["knowledge_gaps"]]
    lines += ["", "## Skill priorities", "", "| Skill | Market demand (1-5) | Level | Evidence | Priority |", "|---|---|---|---|---|"]
    lines += [f"| {g['skill']} | {g['demand']} | {g['level']} | {'measured' if g['measured'] else 'resume estimate'} | {g['priority']} |"
              for g in data["gaps"]]
    lines += ["", "## Preparation plan", "", "| Action | Skill | Due | Done when |", "|---|---|---|---|"]
    lines += [f"| {_cell(a['action'])} | {a['skill']} | {a['due_in_days']} days | {_cell(a['measure'])} |" for a in plan["actions"]]
    lines += ["", "## Recommended resources", ""] + [f"- [{r['title']}]({r['url']})" for r in data["resources"]]
    lines += ["", "## Opportunities", ""]
    for kind, title in KIND_TITLES.items():
        items = data["opportunities"].get(kind, [])
        if not items:
            lines += [f"**{title}:** none found in this run.", ""]
            continue
        lines += [f"**{title}**", "", "| Title | Org | Location | Posted | Fit |", "|---|---|---|---|---|"]
        lines += [f"| [{_cell(i['title'])}]({i['url']}) | {_cell(i['org'])} | {_cell(i['location'])} | {i['posted']} | {i['fit']} |"
                  for i in items]
        lines.append("")
    lines += [f"**Research angle:** {plan['research_angle']}", "", f"**Venture angle:** {plan['venture_angle']}", ""]
    lines += ["## Market analysis", "", "Themes: " + "; ".join(data["market"]["themes"]), ""]
    if data["job_skills"]:
        lines += ["Based on: " + "; ".join(f"{j['title']} at {j['org']}" for j in data["job_skills"]), ""]
    if data["boosted_topics"]:
        lines += [f"**Fed into the daily brief:** {', '.join(data['boosted_topics'])}", ""]
    lines += ["## Session transcript", ""]
    for entry in data["history"]:
        evaluation = entry["evaluation"]
        label = "Follow-up" if entry["is_follow_up"] else f"Question {entry['number']}"
        lines += [f"### {label}: {entry['skill']} ({entry['kind']})", "", entry["prompt"], "",
                  "**Answer:**", "", entry["answer"], "", f"**Score:** {entry['score']}", "",
                  f"**Feedback:** {evaluation['feedback']}", ""]
        lines += [f"- {c['met']}: {c['criterion']} ({c['comment']})" for c in evaluation["criteria"]]
        lines.append("")
    if data["warnings"]:
        lines += ["## Run notes", ""] + [f"- {w}" for w in data["warnings"]]
    return "\n".join(lines) + "\n"


def render_report(data: dict) -> str:
    folder = config.SAMPLES_DIR / "coaching"
    folder.mkdir(parents=True, exist_ok=True)
    text = report_markdown(data)
    prefix = "simulated-" if data["simulated"] else ""
    (folder / f"{prefix}report-{data['session_id']}.md").write_text(text, encoding="utf-8")
    return text
