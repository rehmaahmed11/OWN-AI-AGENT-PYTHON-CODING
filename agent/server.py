"""Self-learning chat GUI server — pure stdlib (http.server, no pip packages).

Serves a mobile-friendly chat UI plus a JSON API:

  GET  /                        -> the chat GUI (single page)
  POST /api/chat     {message, session} -> {reply, learned, mode, chat_id, ...}
  GET  /api/history?session=&limit=     -> past messages
  GET  /api/memory               -> stats + facts + remembered projects
  POST /api/feedback {chat_id, rating}   -> tune style (good/bad)
  POST /api/forget   {kind:'fact', id}   -> delete one learning
  POST /api/build    {task}              -> start a project build (job_id)
  GET  /api/build?id=...                 -> build logs + done flag

Run:  python own_agent.py chat [--port 8765]
On Termux: open http://127.0.0.1:8765 in your phone browser.
"""

from __future__ import annotations

import json
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from . import llm
from .chat import ChatEngine, ChatMemory
from .config import load
from .filesys import Workspace
from .memory import Memory

HTML_PATH = Path(__file__).resolve().parent / "static" / "chat.html"

_cfg: dict = {}
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _engine() -> ChatEngine:
    ws = Workspace(_cfg)
    return ChatEngine(_cfg, ws.roots["workspace"] / "memory.db")


class Handler(BaseHTTPRequestHandler):
    server_version = "OwnAgentChat/1.0"

    # ---------- helpers ----------
    def _send(self, obj, status: int = 200, ctype: str = "application/json"):
        body = obj if isinstance(obj, bytes) else json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            n = 0
        if n <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(min(n, 1_000_000)).decode("utf-8", "replace"))
        except (json.JSONDecodeError, ValueError):
            return {}

    def log_message(self, *a):  # quieter logs
        pass

    # ---------- routes ----------
    def do_GET(self):
        url = urlparse(self.path)
        try:
            if url.path in ("/", "/index.html"):
                html = HTML_PATH.read_text(encoding="utf-8")
                self._send(html.encode("utf-8"), ctype="text/html")
            elif url.path == "/api/history":
                q = parse_qs(url.query)
                session = q.get("session", [""])[0]
                limit = max(1, min(int(q.get("limit", ["60"])[0]), 200))
                eng = _engine()
                try:
                    msgs = eng.mem.history(session=session, limit=limit)
                finally:
                    eng.close()
                self._send({"messages": msgs})
            elif url.path == "/api/memory":
                eng = _engine()
                try:
                    stats = eng.mem.stats()
                    facts = eng.mem.facts()
                    tasks = [{"id": t, "ts": ts, "task": task, "framework": fw}
                             for t, ts, task, fw in eng.projects.list_tasks(limit=20)]
                    self._send({"stats": stats, "facts": facts, "tasks": tasks,
                                "model_up": llm.server_up(_cfg)})
                finally:
                    eng.close()
            elif url.path == "/api/build":
                q = parse_qs(url.query)
                job_id = q.get("id", [""])[0]
                with _jobs_lock:
                    job = _jobs.get(job_id)
                if not job:
                    self._send({"error": "unknown job"}, 404)
                else:
                    self._send({"done": job["done"], "logs": job["logs"],
                                "report": job.get("report"), "error": job.get("error")})
            else:
                self._send({"error": "not found"}, 404)
        except Exception as e:  # never crash the GUI on a bad request
            self._send({"error": f"{e}"}, 500)

    def do_POST(self):
        url = urlparse(self.path)
        try:
            if url.path == "/api/chat":
                data = self._body()
                message = str(data.get("message", ""))
                session = str(data.get("session", "default"))[:32] or "default"
                eng = _engine()
                try:
                    hist = eng.mem.history(session=session, limit=10)
                    out = eng.respond(message, session=session, history=hist)
                finally:
                    eng.close()
                self._send(out)
            elif url.path == "/api/feedback":
                data = self._body()
                eng = _engine()
                try:
                    ok = eng.mem.rate(int(data.get("chat_id", 0)),
                                      str(data.get("rating", "")),
                                      str(data.get("note", "")))
                finally:
                    eng.close()
                self._send({"ok": ok})
            elif url.path == "/api/forget":
                data = self._body()
                eng = _engine()
                try:
                    if data.get("kind") == "fact":
                        ok = eng.mem.forget_fact(int(data.get("id", 0)))
                    else:
                        ok = False
                finally:
                    eng.close()
                self._send({"ok": ok})
            elif url.path == "/api/build":
                from .planner import run_task  # local import: fast startup
                task = str(self._body().get("task", "")).strip()
                if not task:
                    self._send({"error": "empty task"}, 400)
                    return
                if not llm.server_up(_cfg):
                    self._send({"error": "Model server is offline — start it: bash start_model.sh"}, 503)
                    return
                job_id = f"{int(time.time())}-{len(_jobs)}"
                with _jobs_lock:
                    _jobs[job_id] = {"done": False, "logs": [f"🚀 Task: {task}"], "report": None}
                cfg = dict(_cfg)

                def _run():
                    def _log(line: str):
                        with _jobs_lock:
                            _jobs[job_id]["logs"].append(line)
                    try:
                        report = run_task(task, cfg, log=_log)
                        with _jobs_lock:
                            _jobs[job_id]["report"] = {
                                "project_path": report["project_path"],
                                "written": report["written"],
                                "notes": report["notes"],
                            }
                            _jobs[job_id]["logs"].append("✅ Build complete — see 🧠 Memory tab.")
                    except Exception as e:  # noqa: BLE001 — surfaced in GUI
                        with _jobs_lock:
                            _jobs[job_id]["error"] = str(e)
                            _jobs[job_id]["logs"].append(f"❌ {e}\n{traceback.format_exc(limit=2)}")
                    finally:
                        with _jobs_lock:
                            _jobs[job_id]["done"] = True

                threading.Thread(target=_run, daemon=True).start()
                self._send({"job_id": job_id})
            else:
                self._send({"error": "not found"}, 404)
        except Exception as e:  # noqa: BLE001
            self._send({"error": f"{e}"}, 500)


def serve_forever(cfg: dict | None = None, host: str = "0.0.0.0", port: int = 8765) -> None:
    global _cfg
    _cfg = cfg if cfg is not None else load()
    # Touch the DBs so first paint has stats.
    ws = Workspace(_cfg)
    ChatMemory(ws.roots["workspace"] / "memory.db").close()
    Memory(ws.roots["workspace"] / "memory.db").db.close()
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"\n🤖 Self-learning chat GUI running at  http://{host}:{port}")
    print("   On Termux on your phone, open:  http://127.0.0.1:8765")
    print("   Every chat is read, learned from, and tunes future replies. 🧠")
    print("   Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
    # noqa: E722 - intentional silent exit
        print("\n👋 Chat GUI stopped.")


if __name__ == "__main__":
    import sys
    _port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    serve_forever(port=_port)
