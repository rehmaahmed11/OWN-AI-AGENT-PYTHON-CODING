"""All prompts the agent uses.

The bracketed MODE tags ([MODE:PLAN], [MODE:WRITE ...], [MODE:REVIEW]) are
deliberate, stable markers — tests/mock_llm.py keys off them, and they make
the small model's job unambiguous.
"""

from __future__ import annotations

SYSTEM_PROMPT = """You are an expert PYTHON-ONLY coding agent.

Frameworks you use: Flask, FastAPI, Django (web) and Tkinter, PyQt (desktop).
Rules you must always follow:
- Write complete, runnable, production-quality code. Never placeholders, never
  "TODO", never "# rest of code here".
- Stay exactly in scope: deliver what was asked plus the standard parts that
  make that kind of project complete (a company website means Home, About,
  Contact, etc. — nothing more, nothing less).
- Small standard-library-first code, minimal dependencies.
- You cannot execute code yourself, so be precise and consistent across files.
""".strip()


def memory_block(snippets: list[str]) -> str:
    if not snippets:
        return ""
    joined = "\n---\n".join(snippets)
    return (
        "\n\nRelevant lessons from my own past work (reuse these patterns, "
        f"avoid these past mistakes):\n{joined}\n"
    )


def plan_prompt(task: str, snippets: list[str]) -> str:
    return f"""[MODE:PLAN]

Task: {task}

Think like a senior Python developer. Output ONLY a JSON object (no prose, no
markdown fences) with this exact shape:

{{
  "name": "short-project-slug",
  "framework": "flask|fastapi|django|tkinter|pyqt|cli",
  "summary": "one sentence",
  "features": ["every feature and standard page this project needs"],
  "files": [
    {{"path": "relative/path/from/project/root", "purpose": "what this file does"}}
  ]
}}

Requirements:
- The project must be COMPLETE: for websites always include the standard pages
  (e.g. Home, About, Contact — plus the domain-specific ones), templates,
  static assets, requirements.txt and README.md with run instructions.
- For GUI apps: main entry file, separated logic where sensible, README.md.
- Paths are RELATIVE to the project root. Never use ".." or absolute paths.
- Prefer few, well-organized files — this runs on a small device.
{memory_block(snippets)}""".strip()


def write_prompt(plan: dict, file_spec: dict, snippets: list[str]) -> str:
    features = "\n".join(f"- {f}" for f in plan.get("features", []))
    return f"""[MODE:WRITE path={file_spec['path']}]

Project: {plan.get('name')} ({plan.get('framework')}) — {plan.get('summary')}
Features:
{features}

Now write the COMPLETE contents of exactly this one file:
Path: {file_spec['path']}
Purpose: {file_spec['purpose']}

Rules:
- Output exactly ONE code fence (```lang ... ```) and nothing else.
- The file must be complete and runnable — no placeholders, no ellipsis.
- Keep it consistent with the other files of this project (imports, routes,
  template names, static file names).
{memory_block(snippets)}""".strip()


def review_prompt(plan: dict, statuses: list[str], missing: list[str]) -> str:
    status_lines = "\n".join(statuses) or "all files written and non-empty"
    missing_lines = "\n".join(missing) or "none"
    return f"""[MODE:REVIEW]

You planned project "{plan.get('name')}" with these files:
{_file_list(plan)}

Build status:
{status_lines}

Python files with syntax errors (must be fixed):
{missing_lines}

As the senior reviewer: is anything REQUIRED for this project to run still
missing (imports that have no file, templates referenced but not planned,
missing requirements entry)? Output ONLY JSON (no fences):
{{"missing": [{{"path": "...", "purpose": "..."}}]}}
If the project is complete and runnable, output: {{"missing": []}}
Only list files that are strictly required — do not add new features.
""".strip()


def _file_list(plan: dict) -> str:
    return "\n".join(
        f"- {f['path']} ({f.get('purpose', '')})" for f in plan.get("files", [])
    )
