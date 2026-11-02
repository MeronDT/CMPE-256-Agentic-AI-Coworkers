"""Assemble report/Report.md, Report.html and Report.pdf from the static sections and generated results."""
from __future__ import annotations

import base64
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
SAMPLES = ROOT / "samples"
CSS = """
body{font-family:Segoe UI,Arial,sans-serif;max-width:900px;margin:32px auto;padding:0 16px;line-height:1.5;color:#202124}
h1{font-size:26px} h2{margin-top:30px;border-bottom:1px solid #dadce0;padding-bottom:4px} h3{margin-top:22px}
table{border-collapse:collapse;width:100%;margin:12px 0;font-size:14px} th,td{border:1px solid #dadce0;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#f1f3f4} img{max-width:100%} blockquote{border-left:4px solid #dadce0;margin:12px 0;padding:4px 12px;color:#3c4043}
code{background:#f1f3f4;padding:1px 4px;border-radius:3px}
"""


def latest_brief() -> str:
    briefs = sorted((SAMPLES / "briefs").glob("*.md"))
    if not briefs:
        return "*No briefs have been generated yet. Run `scripts/build_deliverables.ps1`.*"
    listing = "\n".join(f"- `samples/briefs/{b.name}`" for b in briefs)
    return f"All generated briefs:\n\n{listing}\n\nThe most recent one is below.\n\n{demote(briefs[-1].read_text(encoding='utf-8'))}"


def latest_session() -> str:
    reports = sorted((SAMPLES / "coaching").glob("report-*.md"))
    if reports:
        listing = "\n".join(f"- `samples/coaching/{r.name}`" for r in reports)
        return ("The answers in this session are my own.\n\n"
                f"All real sessions:\n\n{listing}\n\nThe most recent one is below.\n\n"
                f"{demote(reports[-1].read_text(encoding='utf-8'))}")
    demos = sorted((SAMPLES / "coaching").glob("simulated-report-*.md"))
    if demos:
        return ("> **This is a simulated demonstration, not a real coaching session.** An LLM played the candidate to "
                "show the full interaction. Its scores are not mine and do not count toward my progress.\n\n"
                f"{demote(demos[-1].read_text(encoding='utf-8'))}")
    return "*No coaching session has been completed yet. Run `python -m coworkers coach`.*"


def demote(text: str) -> str:
    """Push a document's headings down so it nests under a report section."""
    text = re.sub(r"<details><summary>Answers</summary>\s*", "**Answers**\n\n", text).replace("</details>", "")
    return re.sub(r"^(#{1,4}) ", lambda m: "#" * (len(m.group(1)) + 2) + " ", text, flags=re.M)


def cost_section() -> str:
    store = Store()
    rows = store.usage_by_purpose()
    if not rows:
        return "No API calls have been made yet."
    table = "\n".join(f"| {r['purpose']} | {r['calls']} | ${r['cost']:.4f} |" for r in rows)
    return f"Total spend: **${store.total_spend():.4f}**\n\n| Step | Calls | Cost |\n|---|---|---|\n{table}"


def main() -> None:
    template = (REPORT / "report_template.md").read_text(encoding="utf-8")
    results = ROOT / "eval" / "RESULTS.md"
    eval_text = demote(results.read_text(encoding="utf-8")) if results.exists() else "*Not run yet.*"
    text = (template.replace("{{SAMPLE_BRIEF}}", latest_brief()).replace("{{SAMPLE_SESSION}}", latest_session())
            .replace("{{EVAL_RESULTS}}", eval_text).replace("{{COST}}", cost_section()))
    (REPORT / "Report.md").write_text(text, encoding="utf-8")
    html = markdown.markdown(text, extensions=["tables", "sane_lists"])

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
