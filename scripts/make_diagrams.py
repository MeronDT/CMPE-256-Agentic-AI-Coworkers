"""Draw the architecture diagrams and export the Mermaid source of the real compiled graphs."""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from coworkers.coach.graph import build_graph as build_coach  # noqa: E402
from coworkers.daily.graph import build_graph as build_daily  # noqa: E402
from coworkers.memory import Store  # noqa: E402

OUT = ROOT / "report"
COLORS = {"node": ("#e8f0fe", "#1a56b0"), "llm": ("#fdeee0", "#b85c00"), "human": ("#e6f4ea", "#1e7a3c"),
          "source": ("#f1f3f4", "#5f6368"), "memory": ("#f3e8fd", "#7627bb"), "output": ("#fff8d6", "#8a6d00")}


def box(ax, x, y, w, h, text, kind="node", size=8.5):
    fill, edge = COLORS[kind]
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.004,rounding_size=0.008", fc=fill, ec=edge, lw=1.2))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=size, color="#202124")
    return x, y, w, h


def arrow(ax, a, b, side=("r", "l"), style="-", color="#3c4043", curve=0.0, label=""):
    def anchor(rect, s):
        x, y, w, h = rect
        return {"r": (x + w, y + h / 2), "l": (x, y + h / 2), "t": (x + w / 2, y + h), "b": (x + w / 2, y)}[s]
    start, end = anchor(a, side[0]), anchor(b, side[1])
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=11, lw=1.1, color=color, linestyle=style,
                                 connectionstyle=f"arc3,rad={curve}", shrinkA=2, shrinkB=2))
    if label:
        ax.text((start[0] + end[0]) / 2, (start[1] + end[1]) / 2 + 0.018, label, ha="center", fontsize=7.5, color=color)


def panel(ax, x, y, w, h, title):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.004,rounding_size=0.01", fc="none", ec="#bdc1c6", lw=0.9, ls="--"))
    ax.text(x + 0.008, y + h - 0.012, title, fontsize=9.5, fontweight="bold", color="#3c4043", va="top")


def legend(ax, y=0.015):
    items = [("node", "Deterministic step"), ("llm", "LLM step"), ("human", "Human in the loop"), ("output", "Output")]
    x = 0.2
    for kind, label in items:
        fill, edge = COLORS[kind]
        ax.add_patch(FancyBboxPatch((x, y), 0.016, 0.016, boxstyle="round,pad=0.001", fc=fill, ec=edge))
        ax.text(x + 0.024, y + 0.008, label, fontsize=8, va="center")
        x += 0.16


def canvas(title):
    fig, ax = plt.subplots(figsize=(13, 7.4))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.text(0.5, 0.975, title, ha="center", fontsize=13, fontweight="bold")
    return fig, ax


def daily_diagram():
    fig, ax = canvas("DailyTechUpgradeAgent architecture")
    panel(ax, 0.01, 0.1, 0.17, 0.83, "Data sources")
    srcs = [box(ax, 0.02, y, 0.15, 0.1, t, "source", 8) for y, t in [
        (0.72, "RSS and Atom\nOpenAI, Google, AWS,\nMicrosoft, IEEE Spectrum,\nHugging Face, LangGraph"),
        (0.55, "Sitemaps and pages\nAnthropic, LangChain,\nIBM Research"),
        (0.38, "Crossref API\nACM CACM, Queue,\nComputing Surveys"),
        (0.21, "arXiv API\ncs.SE, cs.DC, cs.DB")]]
    panel(ax, 0.2, 0.1, 0.6, 0.83, "LangGraph workflow")
    row1, row2 = 0.73, 0.47
    load = box(ax, 0.215, row1, 0.13, 0.09, "load_context\nprofile + memory")
    disc = box(ax, 0.365, row1, 0.13, 0.09, "discover\nfetch, dedupe,\ndate window")
    short = box(ax, 0.515, row1, 0.13, 0.09, "shortlist\nTF-IDF, topics,\nauthority, full text")
    rank_ = box(ax, 0.665, row1, 0.125, 0.09, "rank\nrelevance and\ntechnical depth", "llm")
    sel = box(ax, 0.665, row2, 0.125, 0.09, "select\n3 sources,\n15-20 minutes")
    summ = box(ax, 0.49, row2, 0.13, 0.09, "summarize\ninsights, career value,\nnew concept, recall", "llm", 8)
    ver = box(ax, 0.315, row2, 0.13, 0.09, "verify\nlink, date, quotes\nin source")
    write = box(ax, 0.315, 0.22, 0.13, 0.09, "write\nsave and render")
    brief = box(ax, 0.515, 0.22, 0.2, 0.09, "Daily brief: top 3 articles,\nnew concepts, recall check", "output")
    rate = box(ax, 0.515, 0.13, 0.2, 0.055, "You rate articles (1-5)", "human")
    for a, b in [(load, disc), (disc, short), (short, rank_)]:
        arrow(ax, a, b)
    arrow(ax, rank_, sel, ("b", "t"))
    arrow(ax, sel, summ, ("l", "r"))
    arrow(ax, summ, ver, ("l", "r"))
    arrow(ax, ver, write, ("b", "t"), label="      passed")
    arrow(ax, ver, summ, ("t", "t"), color="#c5221f", curve=-0.5, label="retry once")
    arrow(ax, ver, sel, ("b", "b"), color="#c5221f", curve=0.28)
    ax.text(0.555, 0.355, "rejected: pick a replacement", ha="center", fontsize=7.5, color="#c5221f")
    arrow(ax, write, brief)
    ax.annotate("", xy=(0.365, 0.76), xytext=(0.18, 0.5), arrowprops=dict(arrowstyle="-|>", color="#5f6368", lw=1.1,
                connectionstyle="arc3,rad=-0.2"))
    panel(ax, 0.82, 0.1, 0.17, 0.83, "Memory (SQLite)")
    mem = [box(ax, 0.83, y, 0.15, 0.09, t, "memory", 8) for y, t in [
        (0.73, "Learner profile\nmilestone, interests"), (0.58, "Articles seen\nno repeats"),
        (0.43, "Concept log\nlearning progress"), (0.28, "Briefs and\nLLM cost ledger"),
        (0.13, "Topic weights\nfrom ratings and gaps")]]
    arrow(ax, brief, mem[3], color="#7627bb")
    arrow(ax, brief, rate, ("b", "t"))
    arrow(ax, rate, mem[4], color="#7627bb")
    arrow(ax, mem[0], rank_, ("l", "r"), color="#7627bb")
    ax.text(0.5, 0.875, "Tools: feedparser, trafilatura, scikit-learn TF-IDF, OpenAI structured outputs (hard spending cap)",
            ha="center", fontsize=8.5, style="italic", color="#3c4043")
    legend(ax)
    fig.savefig(OUT / "architecture_daily.png", dpi=170, bbox_inches="tight", facecolor="white")


def coach_diagram():
    fig, ax = canvas("nextLevelPersonalCoachForCareerLevel architecture")
    panel(ax, 0.01, 0.1, 0.17, 0.83, "Data sources")
    srcs = [box(ax, 0.02, y, 0.15, 0.1, t, "source", 8) for y, t in [
        (0.72, "Internships\nSimplify Summer 2027 list"), (0.55, "Job boards\nGreenhouse, Lever, Ashby"),
        (0.38, "Research\narXiv papers"), (0.21, "Venture signals\nHacker News launches")]]
    panel(ax, 0.2, 0.1, 0.6, 0.83, "LangGraph workflow")
    row1, row2 = 0.73, 0.47
    load = box(ax, 0.215, row1, 0.12, 0.09, "load_context\nprofile, scores")
    sct = box(ax, 0.35, row1, 0.12, 0.09, "scout\nfind and score fit")
    ana = box(ax, 0.485, row1, 0.145, 0.09, "analyze\njob posts, blogs,\npapers", "llm")
    gaps = box(ax, 0.645, row1, 0.145, 0.09, "assess_gaps\ndemand x distance\nfrom ready")
    gen = box(ax, 0.645, row2, 0.145, 0.09, "generate_questions\ncoding, design,\nconcept, behavioral", "llm", 8)
    ask = box(ax, 0.47, row2, 0.13, 0.09, "ask\ngraph pauses\nfor your answer", "human")
    eva = box(ax, 0.295, row2, 0.13, 0.09, "evaluate\nrubric verdicts\nand feedback", "llm")
    nxt = box(ax, 0.295, 0.27, 0.13, 0.08, "next_step\nfollow-up or\nnext question")
    rep = box(ax, 0.49, 0.27, 0.13, 0.08, "report\nplan, resources,\nreadiness", "llm")
    out = box(ax, 0.645, 0.27, 0.145, 0.08, "Career Readiness\nReport", "output")
    for a, b in [(load, sct), (sct, ana), (ana, gaps)]:
        arrow(ax, a, b)
    arrow(ax, gaps, gen, ("b", "t"))
    arrow(ax, gen, ask, ("l", "r"))
    arrow(ax, ask, eva, ("l", "r"))
    arrow(ax, eva, nxt, ("b", "t"))
    ax.annotate("", xy=(0.535, 0.47), xytext=(0.425, 0.335), arrowprops=dict(arrowstyle="-|>", color="#c5221f", lw=1.1,
                connectionstyle="arc3,rad=0.2"))
    ax.text(0.545, 0.41, "challenge or next question", fontsize=7.5, color="#c5221f")
    arrow(ax, nxt, rep)
    ax.text(0.457, 0.292, "done", ha="center", fontsize=7.5, color="#3c4043")
    arrow(ax, rep, out)
    ax.annotate("", xy=(0.35, 0.76), xytext=(0.18, 0.5), arrowprops=dict(arrowstyle="-|>", color="#5f6368", lw=1.1,
                connectionstyle="arc3,rad=-0.2"))
    panel(ax, 0.82, 0.1, 0.17, 0.83, "Memory (SQLite)")
    mem = [box(ax, 0.83, y, 0.15, 0.09, t, "memory", 8) for y, t in [
        (0.73, "Learner profile\nresume-based levels"), (0.58, "Measured skill scores\nreplace estimates"),
        (0.43, "Answers and reports\nprogress over time"), (0.28, "Session checkpoints\npause and resume"),
        (0.13, "Topic weights: gaps\nfeed the daily brief")]]
    arrow(ax, rep, mem[4], color="#7627bb", curve=0.12)
    arrow(ax, mem[1], gaps, ("l", "r"), color="#7627bb")
    ax.text(0.5, 0.875, "Tools: job board APIs, deterministic rubric scoring, curated resource list, OpenAI structured outputs",
            ha="center", fontsize=8.5, style="italic", color="#3c4043")
    legend(ax)
    fig.savefig(OUT / "architecture_coach.png", dpi=170, bbox_inches="tight", facecolor="white")


def main():
    daily_diagram()
    coach_diagram()
    store = Store(":memory:")
    (OUT / "graph_daily.mmd").write_text(build_daily(None, store).get_graph().draw_mermaid(), encoding="utf-8")
    (OUT / "graph_coach.mmd").write_text(build_coach(None, store).get_graph().draw_mermaid(), encoding="utf-8")


if __name__ == "__main__":
    main()
