# USAGE GUIDE — Your Own Python Coding Agent on Termux

This is the complete, real-world guide. Follow top to bottom the first time;
after that you only need §3 (everyday use).

---

## 1. What you need

| Thing | Requirement |
|---|---|
| Phone | Android 8+, **~4 GB RAM**, 3 GB free storage |
| App | **Termux from F-Droid** (the Play Store build is outdated/broken) |
| Model | Qwen2.5-Coder-1.5B Q4 (~1.0 GB) — auto-downloaded by the installer |
| Internet | Only for installing packages, downloading the model, and `pip install`-ing generated projects' requirements |
| Patience | On a phone CPU expect roughly 5–15 tokens/sec: a full website takes minutes, not seconds. That's normal. |

---

## 2. First-time setup (once)

```bash
# 1. Get the repo onto the phone
pkg update -y && pkg install -y git
git clone <this-repo-url>
cd OWN-AI-AGENT-PYTHON-CODING

# 2. Run the installer (grabs python, llama.cpp, the ~1GB model,
#    asks you to ALLOW storage access, creates agent_config.json)
bash install_termux.sh
```

If storage permission is requested, tap **Allow** — that is the "local drive
access" you control. Nothing writes there until you approve it in §5.

---

## 3. Everyday use

You work in **two Termux sessions** (swipe from the left edge → *NEW SESSION*).

**Session 1 — the brain (keep running):**
```bash
bash start_model.sh
```
Wait until it says it is listening on `127.0.0.1:8080`.

**Session 2 — you:**
```bash
cd ~/OWN-AI-AGENT-PYTHON-CODING
python own_agent.py doctor          # sanity check: server reachable, roots listed
python own_agent.py "Make a Flask website for a shoes company"
```

You'll watch the loop live:

```
⏳ PLAN  — recalling memory and drafting the project checklist...
✅ PLAN  — flask project 'shoes-company-site', 10 files:
     • app.py — Flask app with all routes
     • templates/base.html — base layout with navbar
     ...
⏳ BUILD [1/10] app.py
✅ BUILD [1/10] app.py (2812 chars, 34s) -> .../workspace/shoes-company-site/app.py
...
⏳ VERIFY — checking files exist and Python syntax is valid...
✅ VERIFY — 10/10 files ok
⏳ REVIEW — asking the model if anything required is missing...
🧠 MEMORY — task saved as #1 (1 total)
================ REPORT ================
Project : shoes-company-site (flask)
Folder  : /data/data/com.termux/files/home/.../workspace/shoes-company-site
Next:
  cd <project folder>
  pip install -r requirements.txt && python app.py   # open http://127.0.0.1:5000
```

Then actually run the generated site (still in Termux):
```bash
cd workspace/shoes-company-site
pip install -r requirements.txt
python app.py
# open http://127.0.0.1:5000 in your phone browser
```

More examples to try:
```bash
python own_agent.py "Tkinter calculator with history panel"
python own_agent.py "FastAPI todo API with SQLite, CRUD endpoints and tests"
python own_agent.py "Django blog with posts, tags and an about page"
```

Useful flags:
- `--no-review` → skip the final model review pass (faster, slightly riskier)
- `--root <name>` → write into another approved root (see §5)

---

## 4. Writing precise tasks (your superpower)

The loop rewards precision. Compare:

❌ `make a shoe site`
✅ `Flask website for a shoes company "ShoeCo": product catalog with prices,
   about page, contact form page, dark blue theme`

The agent still *completes* vague tasks (the system prompt forces standard
pages), but precise tasks give you exactly what you pictured. Mention: the
**framework**, the **subject**, any **pages/features** you care about, and the
**style** if you have one. One or two sentences is plenty.

Second run on a half-good result? Just re-ask with the fix:
`Regenerate the shoes site but add a product detail page with a buy button.`
Files in the workspace get overwritten with the improved version.

---

## 5. Letting it write to your shared storage (your "local drive")

Default safe zone: `workspace/` inside the repo. To also allow a shared
folder (after `termux-setup-storage`):

```bash
mkdir -p /sdcard/SharedProjects
nano agent_config.json
```
```json
"extra_roots": {"shared": "/sdcard/SharedProjects"}
```
Then:
```bash
python own_agent.py "Flask portfolio site" --root shared
```

Hard guarantees (enforced in `agent/filesys.py`):
- the agent can **only** write inside `workspace` + roots you added yourself
- `../` and absolute paths from the model are rejected
- the agent has **no delete or move capability at all** — it can create and
  overwrite files in approved folders, nothing else

---

## 6. The memory (its "self-learning") — and how you curate it

After every task, the agent stores: your request, the plan, the file list,
errors hit and fixes applied (`workspace/memory.db`). Before each new task, the
top-3 relevant past entries are injected into the prompt, so patterns from
YOUR previous working projects get reused.

```bash
python own_agent.py memory list          # see what it remembers
python own_agent.py memory show 3        # full record of task #3
python own_agent.py memory forget 3      # delete a bad/messy run
```

**Your workflow (as you described it): feed only working things.** When a run
produces a project you verified works — great, it stays in memory and becomes
a template for future runs. When a run is a mess — `memory forget <id>` so it
never influences anything. You can also wipe everything:
`rm workspace/memory.db`.

---

## 7. Tuning for 4 GB RAM

`start_model.sh` reads env vars — defaults already fit 4 GB:

```bash
CTX=4096 THREADS=6 bash start_model.sh   # only if your phone copes
```

| Setting | Default | Effect |
|---|---|---|
| `CTX` | 2048 | Context size. Bigger = smarter across files, more RAM. 2048 is safe; 4096 is max recommended on 4 GB. |
| `THREADS` | 4 | CPU threads for the model. Leave 2+ cores for Android or the model gets *slower*. |
| `max_tokens_file` | 1536 | Max length per generated file (in `agent_config.json`). If files look truncated, raise to 2048 and re-run. |
| `max_files` | 25 | Cap on files per project — keeps phone sessions bounded. |

Practical tips:
- **Close other apps** before a big build; Android kills background apps under
  memory pressure (if session 1 dies with "Killed", that was Android's LMK).
- Acquire the wakelock so builds survive screen-off: `termux-wake-lock`
  (from the Termux:API companion app) — optional but recommended.
- Phone will get warm. Long builds on battery are fine, just slower when
  thermal-throttled.

---

## 8. Honest framework notes on Android

- **Flask / FastAPI / Django** — install and run perfectly in Termux
  (`pip install -r requirements.txt` inside the generated project).
- **Tkinter** — installs (`pkg install python-tkinter`), but you need a
  display: **Termux:X11** (recommended) or a VNC server + viewer app.
- **PyQt** — realistically **does not install on Android/Termux** (no wheels;
  building Qt on 4 GB is not viable). The agent will still *write* PyQt
  projects for you — you run them on a PC. It says so in the run hints.

---

## 9. Troubleshooting

| Symptom | Cause → Fix |
|---|---|
| `Cannot reach the model server` | Session 1 not running → `bash start_model.sh`, check with `python own_agent.py doctor` |
| `llama-server` gets `Killed` | Out of RAM → close apps, use `CTX=2048 THREADS=4`, keep the 1.5B Q4 model (don't grab bigger ones) |
| File ends mid-line | Token budget hit → raise `max_tokens_file` in `agent_config.json` (1536→2048) and re-run the task |
| `Model returned an empty file plan` | Small model had a bad moment → just run the same task again (the retry logic catches most cases) |
| Everything is very slow | Normal on CPU. Lower `CTX`, raise `THREADS` up to your core count, or accept it and build overnight |
| Storage permission errors | Re-run `termux-setup-storage`, tap Allow, verify the path in `extra_roots` exists |
| Weird/off-scope output | Your task was vague → be precise (§4). Also `memory forget` the bad run so it doesn't spread |

---

## 10. Upgrading later

- **Stronger model:** when your phone (or patience) allows, try
  Qwen2.5-Coder-3B Q4 (~2 GB) — noticeably better, but tight on 4 GB:
  `MODEL_URL=<3b-url> bash install_termux.sh` then `MODEL=... bash start_model.sh`.
- **True fine-tuning:** not on the phone. If you ever want it, export
  `workspace/memory.db` tasks to a Colab GPU session, LoRA-tune there, convert
  to GGUF, copy back. The RAG memory you already have is the dataset.
- **The agent itself:** it's plain stdlib Python — read `agent/planner.py`;
  it's ~150 lines and is the whole "intelligence" of the workflow.

---

*Remember: on this hardware, intelligence per byte comes from the loop, the
prompt, and your curated memory — not from model size.*
