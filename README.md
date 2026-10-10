# OWN-AI-AGENT-PYTHON-CODING

A **Python-only autonomous coding agent** designed to run on a **4GB Android
phone with Termux**. You describe a project in one sentence; it plans the
complete project, writes every file to real folders on disk, verifies its own
work against a checklist, and remembers what it learns.

- **Scope-locked:** Flask, FastAPI, Django (web) · Tkinter, PyQt (desktop) ·
  plain Python (CLI). Nothing else — it never goes offside.
- **Always complete projects:** "Make a Flask website for a shoes company"
  produces Home / Products / About / Contact, base layout, CSS, 404 page,
  `requirements.txt` and a README — not a fragment.
- **Self-learning without fine-tuning:** every task's plan, files, errors and
  fixes are stored in a local SQLite (FTS5) knowledge base and retrieved before
  the next task (RAG-lite). You curate it: `memory forget <id>`.
- **Safe by design:** writes only inside folders you approve; there is no
  delete/move function; path traversal is rejected.
- **Zero dependencies:** the agent is pure Python 3 standard library. The model
  runs separately via **llama.cpp** (`llama-server`) with a ~1 GB quantized
  code model (Qwen2.5-Coder-1.5B Q4 by default).

## How it works

```
 your task ──> PLAN ──────> BUILD file-by-file ──> VERIFY ──────────> REPORT
               │ JSON checklist  │ writes into      │ files exist,     │ tree +
               │ (features,      │ approved roots   │ ast.parse, model │ run cmd
               │  files)         │                  │ review+fills gaps│
               ▼                  ▼                  ▼                  ▼
            memory (recall) ──────────────────────> memory (save task)
```

The quality comes from this loop + the strict system prompt (`PROMPT.md` /
`agent/prompts.py`), not from model size.

## Quickstart (on your phone)

```bash
pkg update && pkg install -y git
git clone <this-repo-url> && cd OWN-AI-AGENT-PYTHON-CODING
bash install_termux.sh          # installs python + llama.cpp, downloads model
bash start_model.sh             # session 1: serve the model on :8080
# --- new Termux session (swipe from left edge → NEW SESSION) ---
python own_agent.py doctor
python own_agent.py "Make a Flask website for a shoes company"
```

**Full guide: [USAGE.md](USAGE.md)** — precise-task tips, memory curation,
4GB tuning, GUI (Tkinter/PyQt) caveats, troubleshooting.

## Repo map

| Path | What it is |
|---|---|
| `own_agent.py` | CLI launcher |
| `agent/planner.py` | the Plan→Build→Verify→Report loop |
| `agent/prompts.py` | operational prompts (see also `PROMPT.md`) |
| `agent/filesys.py` | file access locked to approved roots |
| `agent/memory.py` | SQLite FTS5 long-term memory |
| `agent/llm.py` | llama.cpp server client (urllib, OpenAI API) |
| `install_termux.sh` / `start_model.sh` | phone setup & model serving |
| `tests/` | offline test suite with a mock model server |

## Dev / tests (any machine, no model needed)

```bash
python -m unittest tests.test_agent -v
```
