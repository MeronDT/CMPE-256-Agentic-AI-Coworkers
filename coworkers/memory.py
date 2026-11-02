"""Long-term memory shared by both agents, stored in SQLite."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles_seen (url TEXT PRIMARY KEY, title TEXT, source TEXT, published TEXT, brief_date TEXT);
CREATE TABLE IF NOT EXISTS briefs (brief_date TEXT PRIMARY KEY, is_replay INTEGER, payload TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS feedback (url TEXT PRIMARY KEY, rating INTEGER, topics TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS topic_weights (topic TEXT PRIMARY KEY, weight REAL);
CREATE TABLE IF NOT EXISTS concepts (name TEXT PRIMARY KEY, explanation TEXT, recall_question TEXT, recall_answer TEXT,
    article_url TEXT, learned_on TEXT);
CREATE TABLE IF NOT EXISTS opportunities (id TEXT PRIMARY KEY, kind TEXT, title TEXT, org TEXT, url TEXT, location TEXT,
    posted TEXT, fit REAL, notes TEXT, found_on TEXT);
CREATE TABLE IF NOT EXISTS answers (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, skill TEXT, kind TEXT, question TEXT,
    answer TEXT, score REAL, evaluation TEXT, simulated INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS skill_scores (session_id TEXT, skill TEXT, score REAL, simulated INTEGER, created_at TEXT,
    PRIMARY KEY (session_id, skill));
CREATE TABLE IF NOT EXISTS reports (session_id TEXT PRIMARY KEY, readiness REAL, payload TEXT, simulated INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS llm_usage (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, model TEXT, input_tokens INTEGER,
    output_tokens INTEGER, cost REAL, purpose TEXT);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path | str | None = None):
        path = path or config.DB_PATH
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.db.executescript(SCHEMA)

    def _write(self, sql: str, params: tuple = ()) -> None:
        with self.lock:
            self.db.execute(sql, params)
            self.db.commit()

    def _rows(self, sql: str, params: tuple = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, params).fetchall()]

    # Daily brief memory
    def seen_urls(self, before: str | None = None) -> set[str]:
        rows = self._rows("SELECT url, brief_date FROM articles_seen")
        return {r["url"] for r in rows if before is None or r["brief_date"] < before}

    def mark_seen(self, url: str, title: str, source: str, published: str, brief_date: str) -> None:
        self._write("INSERT OR REPLACE INTO articles_seen VALUES (?,?,?,?,?)", (url, title, source, published, brief_date))

    def clear_day(self, brief_date: str) -> None:
        """Forget a day's picks, so regenerating it leaves no stale articles or concepts."""
        self._write("DELETE FROM articles_seen WHERE brief_date=?", (brief_date,))
        self._write("DELETE FROM concepts WHERE learned_on=?", (brief_date,))

    def save_brief(self, brief_date: str, is_replay: bool, payload: dict) -> None:
        self._write("INSERT OR REPLACE INTO briefs VALUES (?,?,?,?)",
                    (brief_date, int(is_replay), json.dumps(payload), now()))

    def briefs(self) -> list[dict]:
        rows = self._rows("SELECT * FROM briefs ORDER BY brief_date")
        for row in rows:
            row["payload"] = json.loads(row["payload"])
        return rows

    def topic_weights(self, defaults: dict[str, float]) -> dict[str, float]:
        weights = dict(defaults)
        weights.update({r["topic"]: r["weight"] for r in self._rows("SELECT * FROM topic_weights")})
        return weights

    def set_topic_weight(self, topic: str, weight: float) -> None:
        self._write("INSERT OR REPLACE INTO topic_weights VALUES (?,?)", (topic, round(min(2.0, max(0.3, weight)), 3)))

    def add_feedback(self, url: str, rating: int, topics: list[str], defaults: dict[str, float]) -> None:
        """A 1-5 rating nudges the article's topics up or down."""
        self._write("INSERT OR REPLACE INTO feedback VALUES (?,?,?,?)", (url, rating, json.dumps(topics), now()))
        weights = self.topic_weights(defaults)
        for topic in topics:
            self.set_topic_weight(topic, weights.get(topic, 1.0) + (rating - 3) * 0.1)

    def feedback(self) -> list[dict]:
        return self._rows("SELECT * FROM feedback")

    def add_concept(self, name: str, explanation: str, question: str, answer: str, url: str, learned_on: str) -> bool:
        if self._rows("SELECT 1 FROM concepts WHERE lower(name)=lower(?)", (name,)):
            return False
        self._write("INSERT INTO concepts VALUES (?,?,?,?,?,?)", (name, explanation, question, answer, url, learned_on))
        return True

    def concepts(self) -> list[dict]:
        return self._rows("SELECT * FROM concepts ORDER BY learned_on, name")

    # Coach memory
    def save_opportunities(self, items: list[dict], found_on: str) -> None:
        for item in items:
            self._write("INSERT OR REPLACE INTO opportunities VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (item["id"], item["kind"], item["title"], item["org"], item["url"], item.get("location", ""),
                         item.get("posted", ""), item.get("fit", 0.0), item.get("notes", ""), found_on))

    def save_answer(self, session_id: str, skill: str, kind: str, question: str, answer: str, score: float,
                    evaluation: dict, simulated: bool) -> None:
        self._write("INSERT INTO answers (session_id, skill, kind, question, answer, score, evaluation, simulated, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (session_id, skill, kind, question, answer, score, json.dumps(evaluation), int(simulated), now()))

    def answers(self, session_id: str | None = None) -> list[dict]:
        if session_id:
            return self._rows("SELECT * FROM answers WHERE session_id=? ORDER BY id", (session_id,))
        return self._rows("SELECT * FROM answers ORDER BY id")

    def save_skill_score(self, session_id: str, skill: str, score: float, simulated: bool) -> None:
        self._write("INSERT OR REPLACE INTO skill_scores VALUES (?,?,?,?,?)", (session_id, skill, score, int(simulated), now()))

    def latest_skill_scores(self) -> dict[str, float]:
        """Newest measured score per skill, from real sessions only."""
        rows = self._rows("SELECT skill, score FROM skill_scores WHERE simulated=0 ORDER BY created_at")
        return {r["skill"]: r["score"] for r in rows}

    def skill_history(self) -> list[dict]:
        return self._rows("SELECT * FROM skill_scores WHERE simulated=0 ORDER BY created_at")

    def save_report(self, session_id: str, readiness: float, payload: dict, simulated: bool) -> None:
        self._write("INSERT OR REPLACE INTO reports VALUES (?,?,?,?,?)",
                    (session_id, readiness, json.dumps(payload), int(simulated), now()))

    def reports(self, include_simulated: bool = False) -> list[dict]:
        rows = self._rows("SELECT * FROM reports ORDER BY created_at")
        rows = [r for r in rows if include_simulated or not r["simulated"]]
        for row in rows:
            row["payload"] = json.loads(row["payload"])
        return rows

    # Cost tracking
    def record_usage(self, model: str, input_tokens: int, output_tokens: int, cost: float, purpose: str) -> None:
        self._write("INSERT INTO llm_usage (ts, model, input_tokens, output_tokens, cost, purpose) VALUES (?,?,?,?,?,?)",
                    (now(), model, input_tokens, output_tokens, cost, purpose))

    def total_spend(self) -> float:
        return self._rows("SELECT COALESCE(SUM(cost), 0) AS total FROM llm_usage")[0]["total"]

    def usage_by_purpose(self) -> list[dict]:
        return self._rows("SELECT purpose, COUNT(*) AS calls, SUM(cost) AS cost FROM llm_usage GROUP BY purpose ORDER BY cost DESC")
