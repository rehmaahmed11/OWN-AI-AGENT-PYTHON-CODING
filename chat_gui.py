#!/usr/bin/env python3
"""Launcher for the self-learning chat GUI.

  python chat_gui.py              # web GUI  -> open http://127.0.0.1:8765
  python chat_gui.py --tk         # Tkinter desktop GUI (needs a display)
  python chat_gui.py --port 8081  # web GUI on another port

Every chat is read, stored, learned from, and used to tune future replies. 🧠
"""

import sys

from agent.cli import main

if __name__ == "__main__":
    # Rewrite to: own_agent.py chat [args...]
    raise SystemExit(main(["chat"] + sys.argv[1:]))
