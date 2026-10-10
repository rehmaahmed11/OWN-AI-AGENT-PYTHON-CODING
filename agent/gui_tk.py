"""Desktop chat GUI (Tkinter, stdlib only) for the self-learning agent.

Same brain as the web GUI (agent/chat.py): every message is stored, learned
from, and used to tune the next reply. 👍/👎 buttons tune its style.

Run:  python own_agent.py chat --tk
Needs a display — on Termux use Termux:X11 (see USAGE.md §8).
"""

from __future__ import annotations

import queue
import threading

from .chat import ChatEngine
from .config import load
from .filesys import Workspace


class ChatApp:
    def __init__(self, root, cfg: dict):
        import tkinter as tk
        from tkinter import scrolledtext
        self.tk = tk
        self.cfg = cfg
        ws = Workspace(cfg)
        self.db_path = ws.roots["workspace"] / "memory.db"
        self.session = "desktop"
        self.inbox: queue.Queue = queue.Queue()
        self.last_assistant_id: int | None = None

        root.title("🤖 Own AI Agent — Self-Learning Chat")
        root.geometry("760x560")
        root.minsize(520, 420)

        top = tk.Frame(root)
        top.pack(fill="x", padx=8, pady=(8, 0))
        self.status = tk.Label(top, text="🧠 learning from every chat", anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        tk.Button(top, text="👍", width=3, command=lambda: self.rate("good")).pack(side="left")
        tk.Button(top, text="👎", width=3, command=lambda: self.rate("bad")).pack(side="left")
        tk.Button(top, text="💡 Learned", command=self.show_facts).pack(side="left", padx=(6, 0))

        self.view = scrolledtext.ScrolledText(root, wrap="word", state="disabled",
                                              font=("TkDefaultFont", 11))
        self.view.pack(fill="both", expand=True, padx=8, pady=8)
        for tag, fg in (("me", "#1a56db"), ("bot", "#0f7a3d"), ("sys", "#8a6d00")):
            self.view.tag_config(tag, foreground=fg)

        bottom = tk.Frame(root)
        bottom.pack(fill="x", padx=8, pady=(0, 8))
        self.entry = tk.Entry(bottom, font=("TkDefaultFont", 11))
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda _e: self.send())
        tk.Button(bottom, text="Send", width=10, command=self.send).pack(side="left", padx=(6, 0))

        self.say("bot", "🤖",
                 "Hi! I'm your own AI agent. Every chat is read, remembered and used "
                 "to tune my replies.\nTry: “my name is …”, “I prefer Flask”, then rate me with 👍/👎.")
        self.entry.focus_set()
        root.after(100, self._pump)

    # ---------- UI helpers ----------
    def say(self, tag: str, who: str, text: str):
        self.view.configure(state="normal")
        self.view.insert("end", f"{who}: ", tag)
        self.view.insert("end", text + "\n\n")
        self.view.configure(state="disabled")
        self.view.see("end")

    def _pump(self):
        try:
            while True:
                kind, payload = self.inbox.get_nowait()
                if kind == "reply":
                    self.last_assistant_id = payload["chat_id"]
                    mode = "🟢" if payload["mode"] == "llm" else "📴 offline-memory"
                    self.status.config(text=f"{mode}  •  🧠 facts: {payload['facts_count']}"
                                            f"  •  recalled: {payload['recalled']} past chats")
                    self.say("bot", "🤖", payload["reply"])
                    for f in payload["learned"]:
                        self.say("sys", "🧠", f"learned: {f['key']} = {f['value']}")
                elif kind == "error":
                    self.say("sys", "⚠️", payload)
        except queue.Empty:
            pass
        self.view.after(100, self._pump)

    # ---------- actions ----------
    def send(self):
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        self.say("me", "🧑", text)
        self.say("sys", "⏳", "thinking & recalling memory…")
        threading.Thread(target=self._ask, args=(text,), daemon=True).start()

    def _ask(self, text: str):
        eng = ChatEngine(self.cfg, self.db_path)
        try:
            hist = eng.mem.history(session=self.session, limit=10)
            out = eng.respond(text, session=self.session, history=hist)
            self.inbox.put(("reply", out))
        except Exception as e:  # noqa: BLE001 — shown in GUI
            self.inbox.put(("error", str(e)))
        finally:
            eng.close()

    def rate(self, rating: str):
        if not self.last_assistant_id:
            self.say("sys", "ℹ️", "No reply to rate yet — chat first!")
            return
        eng = ChatEngine(self.cfg, self.db_path)
        try:
            eng.mem.rate(self.last_assistant_id, rating)
        finally:
            eng.close()
        msg = "Noted — I'll do more of that! 👍" if rating == "good" else "Noted — tuning away from that style. 👎"
        self.say("sys", "🧠", msg)

    def show_facts(self):
        eng = ChatEngine(self.cfg, self.db_path)
        try:
            facts = eng.mem.facts()
            stats = eng.mem.stats()
        finally:
            eng.close()
        if not facts:
            self.say("sys", "💡", "Nothing learned yet — tell me “my name is …”!")
            return
        lines = [f"• {f['key']} = {f['value']}  (×{f['confidence']})" for f in facts]
        lines.append(f"\n📊 {stats['chats']} chats • 👍{stats['good']} 👎{stats['bad']}")
        self.say("sys", "💡", "What I've learned about you:\n" + "\n".join(lines))


def main(cfg: dict | None = None) -> int:
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("❌ Tkinter is not installed.\n"
              "   Termux: pkg install python-tkinter  (+ Termux:X11 for display)\n"
              "   PC: it ships with most Pythons; on Debian: sudo apt install python3-tk\n"
              "  Tip: the web GUI needs no display:  python own_agent.py chat")
        return 1
    import tkinter as tk
    cfg = cfg if cfg is not None else load()
    root = tk.Tk()
    ChatApp(root, cfg)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
