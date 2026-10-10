"""The agent's long-term memory — this is its 'self-learning'.

No training, no fine-tuning: after every task the agent stores the plan, the
file tree it produced, and notes (errors hit, fixes applied, your feedback)
into a SQLite database with FTS5 full-text search. Before a new task, the most
relevant past entries are retrieved and injected into the prompt (RAG-lite).

Because YOU control what gets remembered, feeding it only precise, working
results keeps its future output clean — garbage in, garbage out works both
ways, so `memory forget <id>` is your curation tool.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    task TEXT NOT NULL,
    framework TEXT,
    summary TEXT,
    plan_json TEXT,
    files_json TEXT,
    notes TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(task, content);
"""


class Memory:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(db_path))
        self.db.executescript(_SCHEMA)

    def save_task(self, task: str, plan: dict, files: list[str], notes: str) -> int:
        cur = self.db.execute(
            "INSERT INTO tasks (ts, task, framework, summary, plan_json, files_json, notes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                time.time(),
                task,
                plan.get("framework", ""),
                plan.get("summary", ""),
                json.dumps(plan, ensure_ascii=False),
                json.dumps(files, ensure_ascii=False),
                notes,
            ),
        )
        task_id = cur.lastrowid
        fts_content = (
            f"framework: {plan.get('framework', '')}\n"
            f"features: {', '.join(plan.get('features', []))}\n"
            f"files: {', '.join(files)}\n"
            f"notes: {notes}"
        )
        self.db.execute(
            "INSERT INTO memory_fts (rowid, task, content) VALUES (?, ?, ?)",
            (task_id, task, fts_content),
        )
        self.db.commit()
        return int(task_id)

    def recall(self, query: str, k: int = 3) -> list[str]:
        """Keyword search (FTS5). Returns up to k formatted past-task snippets."""
        words = [w for w in re.findall(r"[A-Za-z0-9_]{3,}", query.lower())][:8]
        if not words:
            return []
        match = " OR ".join(f'"{w}"' for w in words)
        try:
            rows = self.db.execute(
                "SELECT t.task, t.framework, t.files_json, t.notes"
                " FROM memory_fts f JOIN tasks t ON t.id = f.rowid"
                " WHERE memory_fts MATCH ? ORDER BY rank LIMIT ?",
                (match, k),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        snippets = []
        for task, framework, files_json, notes in rows:
            files = ", ".join(json.loads(files_json or "[]")[:12])
            snippets.append(
                f"Past task: {task}\nframework: {framework}\n"
                f"files used: {files}\nnotes: {notes}"
            )
        return snippets

    def list_tasks(self, limit: int = 20) -> list[tuple]:
        return self.db.execute(
            "SELECT id, datetime(ts, 'unixepoch', 'localtime'), task, framework"
            " FROM tasks ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()

    def show(self, task_id: int) -> dict | None:
        row = self.db.execute(
            "SELECT task, framework, summary, plan_json, files_json, notes"
            " FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        if not row:
            return None
        task, framework, summary, plan_json, files_json, notes = row
        return {
            "task": task,
            "framework": framework,
            "summary": summary,
            "plan": json.loads(plan_json or "{}"),
            "files": json.loads(files_json or "[]"),
            "notes": notes,
        }

    def forget(self, task_id: int) -> bool:
        """Remove one remembered task (your curation tool)."""
        cur = self.db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self.db.execute("DELETE FROM memory_fts WHERE rowid = ?", (task_id,))
        self.db.commit()
        return cur.rowcount > 0

    def count(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0])
