# Agentic AI Coworkers

Two personal agents built with LangGraph that share one memory:

- **DailyTechUpgradeAgent** finds three technical articles a day and turns them into a 15–20 minute brief with a new concept and a recall check.
- **nextLevelPersonalCoachForCareerLevel** finds opportunities, questions you interactively, grades your answers and writes a Career Readiness Report.

The full write-up is in [report/Report.pdf](report/Report.pdf).

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

Put your OpenAI key in `.env` (see `.env.example`), then confirm it works:

```powershell
.\.venv\Scripts\python -m coworkers check
```

## Usage

```powershell
.\.venv\Scripts\python -m coworkers daily           # today's brief
.\.venv\Scripts\python -m coworkers rate            # rate it to personalize future briefs
.\.venv\Scripts\python -m coworkers coach           # start a coaching session
.\.venv\Scripts\python -m coworkers opportunities   # matched opportunities, no API cost
.\.venv\Scripts\python -m coworkers status          # progress and API spend
.\.venv\Scripts\streamlit run app.py                # web app for all of the above
```

Edit [profile.yaml](profile.yaml) to change the milestone, interests or skills.

## Regenerate the deliverables

```powershell
.\scripts\build_deliverables.ps1              # sample briefs, evaluation, diagrams and report
.\scripts\build_deliverables.ps1 -ReportOnly  # after a coaching session, refresh the report
```

## Run it every morning

```powershell
schtasks /Create /SC DAILY /ST 08:00 /TN DailyTechUpgrade /TR "powershell -File $PWD\scripts\run_daily.ps1"
```

## Layout

| Path | Contents |
|---|---|
| `coworkers/daily/` | Agent 1: sources, ranking, graph, brief renderer |
| `coworkers/coach/` | Agent 2: opportunities, scoring, graph, report renderer |
| `coworkers/memory.py` | Shared SQLite memory |
| `coworkers/llm.py` | OpenAI wrapper with retries and the spending cap |
| `eval/` | Evaluation harness, fixtures and results |
| `samples/` | Generated briefs and coaching reports |
| `report/` | Report, architecture diagrams and Mermaid exports of the real graphs |
| `tests/` | Tests that run without an API key |

Spending stops at `BUDGET_USD`, which defaults to $2.00.
