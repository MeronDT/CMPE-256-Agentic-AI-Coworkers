"""Assemble report/Report.md, Report.html and Report.pdf from the template and generated results."""
from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from coworkers.memory import Store  # noqa: E402

REPORT = ROOT / "report"
REPO = "https://github.com/MeronDT/CMPE-256-Agentic-AI-Coworkers/blob/main"
CSS = """
body{font-family:Segoe UI,Arial,sans-serif;max-width:860px;margin:24px auto;padding:0 16px;line-height:1.45;color:#202124;font-size:14px}
h1{font-size:24px;margin-bottom:4px} h2{margin-top:24px;border-bottom:1px solid #dadce0;padding-bottom:3px;font-size:19px} h3{margin:14px 0 6px;font-size:15px}
h2:not(:first-of-type){page-break-before:always;margin-top:0}
table{border-collapse:collapse;width:100%;margin:10px 0;font-size:13px} th,td{border:1px solid #dadce0;padding:5px 7px;text-align:left;vertical-align:top}
th{background:#f1f3f4} img{max-width:100%;page-break-inside:avoid;margin:6px 0} ul{margin:6px 0;padding-left:22px}
code{background:#f1f3f4;padding:1px 4px;border-radius:3px} pre{background:#f1f3f4;padding:8px;font-size:12px;white-space:pre-wrap} pre code{padding:0}
"""


def cell(text: str) -> str:
    return text.replace("|", "/").replace("\n", " ")


def first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])(?<!vs\.)\s+(?=[A-Z])", text.strip())[0]


def daily_prototype(brief: dict) -> str:
    titles = "\n".join(f"{n}. {i['title']}" for n, i in enumerate(brief["items"], 1))
    return (f"The agent runs with one command. This is shortened output from the live run on {brief['date']}:\n\n"
            f"```text\n> python -m coworkers daily\n\nDaily Technical Learning Brief: {brief['date']}\n"
            f"Reading session: about {brief['total_minutes']} minutes\n"
            f"Chosen from {brief['fresh_candidates']} new articles in the last 7 days\n\n{titles}\n```")


def daily_results(brief: dict, count: int) -> str:
    rows = "\n".join(f"| [{cell(i['title'])}]({i['url']}) | {i['source']}, {i['published']} | "
                     f"{cell(first_sentence(i['career_contribution']))} |" for i in brief["items"])
    first = brief["items"][0]
    return (f"| Article | Source | Why it is relevant |\n|---|---|---|\n{rows}\n\n"
            f"**Example summary, article 1:** {first['summary']}\n\n"
            f"[All {count} full briefs]({REPO}/samples/briefs)")


def daily_eval(results: dict) -> str:
    d, p = results["daily"], results["personalization"]
    overlap = max(p["shortlist_overlap_pct"].values())
    return (f"- **Effectiveness:** does each brief deliver three articles in a 15–20 minute session, and do different "
            f"interests change the picks? {d['full_briefs']} of {d['briefs']} briefs did, and shortlists for different "
            f"profiles overlapped by at most {overlap:.0f}%.\n"
            f"- **Accuracy:** are the links, dates and summaries correct? All links and dates checked out, every evidence "
            f"quote appeared in its source, and an independent LLM check supported {d['claims_supported_pct']}% of "
            f"{d['claims_judged']} claims.\n"
            f"- **User progress:** concepts logged and article ratings over time. So far that is {d['concepts_logged']} "
            f"concepts and {d['user_ratings']} ratings.")


def coach_prototype(data: dict) -> str:
    first = data["history"][0]
    follow = data["history"][1] if len(data["history"]) > 1 and data["history"][1]["is_follow_up"] else None
    text = (f"The coach asks one question at a time and responds to each answer. This is from my own session:\n\n"
            f"**Coach ({first['kind']} question):** {first['prompt']}\n\n"
            f"**My answer:**\n\n```text\n{first['answer']}\n```\n\n"
            f"**Coach's evaluation, {first['score']:.0f}/100:** {first['evaluation']['feedback']}")
    if follow:
        text += f"\n\n**Coach's follow-up:** {follow['prompt']}"
    return text


def coach_results(data: dict, count: int) -> str:
    answered = [h for h in data["history"] if h["answer"].strip().lower() not in {"", "skip", "pass", "idk"}]
    tried = {h["skill"] for h in answered}
    evidence = lambda g: "answered" if g["skill"] in tried else "skipped" if g["measured"] else "resume estimate"  # noqa: E731
    rows = "\n".join(f"| {g['skill']} | {g['level']:.2f} | {evidence(g)} |" for g in data["gaps"][:4])
    openings = "; ".join(f"[{i['org']}]({i['url']})" for i in data["opportunities"]["internship"][:3])
    resource = data["resources"][0]["title"] if data["resources"] else "none selected"
    action = data["plan"]["actions"][0]["action"]
    return (f"I answered {len(answered)} of {len(data['history'])} prompts and skipped the rest for time, so this is a "
            f"baseline. Skipped prompts score 0.\n\n"
            f"**Readiness for a Summer 2027 internship:** {data['readiness']['score']}/100 after {count} session. Each new "
            f"session is saved and compared with the last.\n\n"
            f"| Biggest gaps | Level (0–1) | Evidence |\n|---|---|---|\n{rows}\n\n"
            f"**Matched internships include:** {openings}.\n\n**Recommended resource:** {resource}. "
            f"**First planned step:** {action}\n\n"
            f"[Full Career Readiness Report and transcript]({REPO}/samples/coaching/report-{data['session_id']}.md)")


def coach_eval(results: dict, data: dict) -> str:
    coach = results["coach"]
    e, s = coach["extraction"], coach["calibration"]
    return (f"- **Effectiveness:** can grading tell good answers from bad ones? On {s['questions']} questions with seeded "
            f"answers, strong always beat partial and partial beat wrong, while confident bluffs and prompt injections "
            f"scored {s['injection_max_score']:.0f}.\n"
            f"- **Accuracy:** does it read job posts correctly? Skill extraction scored F1 {e['f1']} on {e['posts']} "
            f"hand-labeled test posts.\n"
            f"- **User progress:** readiness and skill scores across sessions. My baseline is "
            f"{data['readiness']['score']}/100, and a second session is needed to show change.")


def main() -> None:
    store = Store()
    template = (REPORT / "report_template.md").read_text(encoding="utf-8")
    briefs = store.briefs()
    reports = store.reports()
    if not briefs or not reports:
        sys.exit("The report needs at least one brief and one real coaching session.")
    brief, data = briefs[-1]["payload"], reports[-1]["payload"]
    results = json.loads((ROOT / "eval" / "results.json").read_text(encoding="utf-8"))
    parts = {"DAILY_PROTOTYPE": daily_prototype(brief), "DAILY_RESULTS": daily_results(brief, len(briefs)),
             "DAILY_EVAL": daily_eval(results), "COACH_PROTOTYPE": coach_prototype(data),
             "COACH_RESULTS": coach_results(data, len(reports)), "COACH_EVAL": coach_eval(results, data)}
    text = template
    for name, value in parts.items():
        text = text.replace("{{" + name + "}}", value)
    (REPORT / "Report.md").write_text(text, encoding="utf-8")
    html = markdown.markdown(text, extensions=["tables", "sane_lists", "fenced_code"])

    def embed(match: re.Match) -> str:
        data = base64.b64encode((REPORT / match.group(1)).read_bytes()).decode()
        return f'src="data:image/png;base64,{data}"'

    html = re.sub(r'src="([^":]+\.png)"', embed, html)
    page = f"<!doctype html><html><head><meta charset='utf-8'><title>Agentic AI Coworkers</title><style>{CSS}</style></head><body>{html}</body></html>"
    html_path = REPORT / "Report.html"
    html_path.write_text(page, encoding="utf-8")
    edge = shutil.which("msedge") or r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    if Path(edge).exists():
        subprocess.run([edge, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={REPORT / 'Report.pdf'}", html_path.as_uri()], check=False, timeout=90,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("PDF written" if (REPORT / "Report.pdf").exists() else "PDF skipped, Report.html is available")


if __name__ == "__main__":
    main()
