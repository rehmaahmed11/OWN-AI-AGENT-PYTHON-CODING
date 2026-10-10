"""The agent loop: PLAN -> BUILD -> VERIFY -> REMEMBER -> REPORT.

This orchestrator is where 'understands well and never goes offside' comes
from — not from model size. The small model is forced through a checklist
(plan), builds one file at a time, then must pass deterministic checks
(file exists, Python parses) plus its own completeness review.
"""

from __future__ import annotations

import ast
import json
import re
import time

from . import llm, prompts
from .filesys import Workspace
from .memory import Memory

MAX_REVIEW_FIXES = 3


def extract_json(text: str) -> dict:
    """Pull the first {...} object out of model output."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object found")
    return json.loads(text[start : end + 1])


def extract_code(text: str) -> str:
    """Return the content of the first code fence, or the whole trimmed text."""
    m = re.search(r"```[A-Za-z0-9_+-]*\n(.*?)```", text, re.S)
    code = m.group(1) if m else text
    return code.rstrip() + "\n"


def _chat(system_plus_user: list[dict], cfg: dict, max_tokens: int) -> str:
    return llm.chat(system_plus_user, cfg, max_tokens=max_tokens)


def run_task(
    task: str,
    cfg: dict,
    root_name: str = "workspace",
    review: bool | None = None,
    log=print,
) -> dict:
    review = cfg.get("review", True) if review is None else review
    ws = Workspace(cfg)
    mem = Memory(ws.roots["workspace"] / "memory.db")
    system = [{"role": "system", "content": prompts.SYSTEM_PROMPT}]

    # ---------- 1. PLAN ----------
    log("⏳ PLAN  — recalling memory and drafting the project checklist...")
    snippets = mem.recall(task, k=cfg["memory_results"])
    plan_msg = system + [{"role": "user", "content": prompts.plan_prompt(task, snippets)}]
    raw = _chat(plan_msg, cfg, cfg["max_tokens_plan"])
    try:
        plan = extract_json(raw)
    except ValueError:
        # One retry, asked to be strict.
        raw = _chat(plan_msg + [{"role": "assistant", "content": raw},
                                {"role": "user", "content": "Output ONLY the JSON object now."}],
                    cfg, cfg["max_tokens_plan"])
        plan = extract_json(raw)

    files = _sanitize_files(plan, cfg["max_files"])
    plan["files"] = files
    project_dir = slug(plan.get("name") or "project")
    log(f"✅ PLAN  — {plan.get('framework', '?')} project '{project_dir}', "
        f"{len(files)} files:")
    for f in files:
        log(f"     • {f['path']} — {f.get('purpose', '')}")

    # ---------- 2. BUILD ----------
    written: list[str] = []
    notes: list[str] = []
    for i, spec in enumerate(files, 1):
        rel = f"{project_dir}/{spec['path']}"
        log(f"⏳ BUILD [{i}/{len(files)}] {spec['path']}")
        t0 = time.time()
        out = _chat(system + [{"role": "user", "content": prompts.write_prompt(plan, spec, snippets)}],
                    cfg, cfg["max_tokens_file"])
        code = extract_code(out)
        path = ws.write_text(root_name, rel, code)
        written.append(rel)
        log(f"✅ BUILD [{i}/{len(files)}] {spec['path']} "
            f"({len(code)} chars, {time.time() - t0:.0f}s) -> {path}")

    # ---------- 3. VERIFY (deterministic) ----------
    log("⏳ VERIFY — checking files exist and Python syntax is valid...")
    statuses, syntax_bad = [], []
    for f in files:
        rel = f"{project_dir}/{f['path']}"
        if not ws.exists_nonempty(root_name, rel):
            statuses.append(f"MISSING/EMPTY: {rel}")
        else:
            statuses.append(f"ok: {rel}")
        if f["path"].endswith(".py"):
            src = ws.resolve(root_name, rel).read_text(encoding="utf-8", errors="replace")
            try:
                ast.parse(src)
            except SyntaxError as e:
                syntax_bad.append(rel)
                notes.append(f"syntax error in {rel}: {e}")
    log(f"✅ VERIFY — {sum(1 for s in statuses if s.startswith('ok'))}/{len(files)} files ok"
        + (f", syntax errors: {syntax_bad}" if syntax_bad else ""))

    # ---------- 3b. VERIFY (model review + fix gaps) ----------
    if review:
        log("⏳ REVIEW — asking the model if anything required is missing...")
        raw = _chat(system + [{"role": "user", "content": prompts.review_prompt(plan, statuses, syntax_bad)}],
                    cfg, cfg["max_tokens_review"])
        try:
            missing = extract_json(raw).get("missing", [])[:MAX_REVIEW_FIXES]
        except ValueError:
            missing = []
            notes.append("review step returned unparseable output; skipped")
        for spec in missing:
            rel_path = str(spec.get("path", "")).strip()
            if not rel_path:
                continue
            rel = f"{project_dir}/{rel_path}"
            if ws.exists_nonempty(root_name, rel):
                continue
            log(f"⏳ FIX    — adding missing file {rel_path}")
            out = _chat(system + [{"role": "user", "content": prompts.write_prompt(plan, spec, snippets)}],
                        cfg, cfg["max_tokens_file"])
            ws.write_text(root_name, rel, extract_code(out))
            written.append(rel)
            notes.append(f"review added missing file: {rel}")
            log(f"✅ FIX    — wrote {rel}")

    # ---------- 4. REMEMBER ----------
    mem_id = mem.save_task(task, plan, written, "; ".join(notes) or "clean run")
    log(f"🧠 MEMORY — task saved as #{mem_id} ({mem.count()} total)")

    return {
        "plan": plan,
        "project_dir": project_dir,
        "root": root_name,
        "project_path": str(ws.resolve(root_name, project_dir)),
        "written": written,
        "syntax_errors": syntax_bad,
        "notes": notes,
        "memory_id": mem_id,
    }


def _sanitize_files(plan: dict, cap: int) -> list[dict]:
    seen, out = set(), []
    for f in plan.get("files", []):
        path = str(f.get("path", "")).strip().lstrip("/")
        if not path or path in seen or ".." in path.split("/"):
            continue
        seen.add(path)
        out.append({"path": path, "purpose": str(f.get("purpose", ""))[:200]})
        if len(out) >= cap:
            break
    if not out:
        raise ValueError("Model returned an empty file plan. Rephrase your task and try again.")
    return out


def slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return s or "project"


RUN_HINTS = {
    "flask": "pip install -r requirements.txt && python app.py  # open http://127.0.0.1:5000",
    "fastapi": "pip install -r requirements.txt && uvicorn main:app --reload  # http://127.0.0.1:8000/docs",
    "django": "pip install -r requirements.txt && python manage.py migrate && python manage.py runserver",
    "tkinter": "python main.py  # on Termux needs Termux:X11 or a VNC viewer",
    "pyqt": "python main.py  # PyQt generally does not install on Android; run on PC",
    "cli": "python main.py",
}


def run_hint(framework: str) -> str:
    return RUN_HINTS.get((framework or "").lower(), RUN_HINTS["cli"])
