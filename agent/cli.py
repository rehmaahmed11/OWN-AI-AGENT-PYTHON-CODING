"""Command line interface.

  python own_agent.py "Make a Flask website for a shoes company"
  python own_agent.py run "..." [--root shared] [--no-review]
  python own_agent.py memory list | show <id> | forget <id>
  python own_agent.py doctor
  python own_agent.py chat [--port 8765] [--tk]
"""

from __future__ import annotations

import argparse
import sys

from .config import load
from .filesys import Workspace
from .memory import Memory
from .planner import run_hint, run_task
from . import llm

KNOWN = {"run", "memory", "doctor", "chat"}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Convenience: treat "own_agent.py <some task text>" as `run`.
    if argv and argv[0] not in KNOWN and not argv[0].startswith("-"):
        argv = ["run"] + argv

    p = argparse.ArgumentParser(prog="own_agent", description="Python-only coding agent")
    sub = p.add_subparsers(dest="cmd")

    pr = sub.add_parser("run", help="run one task")
    pr.add_argument("task", nargs="+", help="what to build")
    pr.add_argument("--root", default="workspace",
                    help="approved root to write into (default: workspace)")
    pr.add_argument("--no-review", action="store_true", help="skip the model review pass")

    pm = sub.add_parser("memory", help="inspect/clean the agent's memory")
    pm.add_argument("action", choices=["list", "show", "forget"])
    pm.add_argument("id", type=int, nargs="?")

    sub.add_parser("doctor", help="check config and model server")

    pc = sub.add_parser("chat", help="open the self-learning chat GUI")
    pc.add_argument("--port", type=int, default=8765, help="web GUI port (default: 8765)")
    pc.add_argument("--host", default="0.0.0.0", help="web GUI host (default: 0.0.0.0)")
    pc.add_argument("--tk", action="store_true", help="use the Tkinter desktop GUI instead of the web GUI")

    args = p.parse_args(argv)
    if args.cmd is None:
        p.print_help()
        return 0

    cfg = load()

    if args.cmd == "run":
        task = " ".join(args.task).strip()
        if not task:
            print("Empty task.")
            return 1
        ws = Workspace(cfg)
        if args.root not in ws.roots:
            print(f"Root '{args.root}' not approved. Available: {', '.join(ws.available_roots())}")
            print('Approve more via "extra_roots" in agent_config.json.')
            return 1
        print(f"🤖 OWN-AI-AGENT — task: {task}\n   root: {args.root} -> {ws.roots[args.root]}\n")
        try:
            report = run_task(task, cfg, root_name=args.root, review=not args.no_review)
        except llm.LLMError as e:
            print(f"\n❌ {e}")
            return 2
        except ValueError as e:
            print(f"\n❌ {e}")
            return 2

        print("\n================ REPORT ================")
        print(f"Project : {report['plan'].get('name')} ({report['plan'].get('framework')})")
        print(f"Folder  : {report['project_path']}")
        print("Files   :")
        for rel in report["written"]:
            print(f"  - {rel}")
        if report["syntax_errors"]:
            print(f"⚠️  Python syntax problems: {report['syntax_errors']}")
        if report["notes"]:
            print("Notes   : " + " | ".join(report["notes"]))
        print("\nNext:")
        print(f"  cd {report['project_path']}")
        print(f"  {run_hint(report['plan'].get('framework', 'cli'))}")
        return 0

    if args.cmd == "memory":
        ws = Workspace(cfg)
        mem = Memory(ws.roots["workspace"] / "memory.db")
        if args.action == "list":
            rows = mem.list_tasks()
            if not rows:
                print("Memory is empty — run a task first.")
            for tid, ts, task, framework in rows:
                print(f"#{tid:<3} [{ts}] ({framework}) {task[:80]}")
            print(f"\n{mem.count()} task(s) remembered.")
        elif args.action == "show":
            if args.id is None:
                print("Usage: memory show <id>")
                return 1
            item = mem.show(args.id)
            if not item:
                print(f"No task #{args.id}.")
                return 1
            print(f"Task #{args.id}: {item['task']}\nFramework: {item['framework']}\n"
                  f"Summary: {item['summary']}\nFiles:")
            for f in item["files"]:
                print(f"  - {f}")
            print(f"Notes: {item['notes']}")
        elif args.action == "forget":
            if args.id is None:
                print("Usage: memory forget <id>")
                return 1
            print("Removed." if mem.forget(args.id) else f"No task #{args.id}.")
        return 0

    if args.cmd == "chat":
        if args.tk:
            from .gui_tk import main as tk_main
            return tk_main(cfg)
        from .server import serve_forever
        if not llm.server_up(cfg):
            print("📴 Model server is offline — chat still works in memory mode (it learns,\n"
                  "   answers from what it knows about you), but start the model for full\n"
                  "   answers:  bash start_model.sh\n")
        serve_forever(cfg, host=args.host, port=args.port)
        return 0

    if args.cmd == "doctor":
        ws = Workspace(cfg)
        print(f"Model server : {cfg['base_url']}  ->  "
              + ("✅ reachable" if llm.server_up(cfg)
                 else "❌ NOT reachable — start it: bash start_model.sh"))
        print(f"Roots        : {', '.join(f'{n}={p}' for n, p in ws.roots.items())}")
        print(f"Budgets      : file={cfg['max_tokens_file']} tok, "
              f"max_files={cfg['max_files']}, timeout={cfg['timeout_s']}s")
        mem = Memory(ws.roots["workspace"] / "memory.db")
        print(f"Memory       : {mem.count()} task(s) remembered")
        return 0

    return 0
