"""Tests for the self-learning chat engine (agent/chat.py) — all offline.

Run:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.chat import ChatEngine, ChatMemory, extract_facts
from agent.config import DEFAULTS
from tests.mock_llm import serve


class LearnExtractTest(unittest.TestCase):
    def test_name_role_likes(self):
        facts = dict(extract_facts("Hi, my name is Ahmed. I am a student. I love Flask."))
        self.assertEqual(facts.get("name"), "Ahmed")
        self.assertEqual(facts.get("role"), "student")
        self.assertEqual(facts.get("likes"), "Flask")

    def test_prefer_project_remember(self):
        facts = dict(extract_facts(
            "I prefer dark mode. I'm building a shoes website. "
            "Remember that my shop opens in June."))
        self.assertEqual(facts.get("prefers"), "dark mode")
        self.assertEqual(facts.get("project"), "a shoes website")
        self.assertIn("shop opens in June", facts.get("note", ""))

    def test_no_false_positives_on_questions(self):
        self.assertEqual(extract_facts("what is my name?"), [])
        self.assertEqual(extract_facts("do you like pizza?"), [])


class ChatEngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = serve(0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chat-test-"))
        self.cfg = dict(DEFAULTS)
        self.cfg["base_url"] = f"http://127.0.0.1:{self.port}"
        self.cfg["workspace"] = str(self.tmp / "workspace")
        self.cfg["timeout_s"] = 10
        (self.tmp / "workspace").mkdir(parents=True)
        self.db = self.tmp / "workspace" / "memory.db"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_chat_learns_and_tunes_prompt(self):
        eng = ChatEngine(self.cfg, self.db)
        try:
            # 1st chat teaches the name...
            out1 = eng.respond("my name is Ahmed", session="t1")
            self.assertEqual(out1["mode"], "llm")
            self.assertTrue(any(f["key"] == "name" and f["value"] == "Ahmed"
                                for f in out1["learned"]), out1)
            # ...and the 2nd reply's tuned prompt already contains it
            # (the mock echoes the learned profile back to us).
            out2 = eng.respond("what is my name?", session="t1")
            self.assertIn("Ahmed", out2["reply"])
            # Chats were stored and are recallable.
            self.assertGreaterEqual(len(eng.mem.recall_chats("what is my name", 1)), 1)
            self.assertEqual(eng.mem.stats()["chats"], 4)  # 2 exchanges x 2 roles
        finally:
            eng.close()

    def test_offline_mode_answers_from_memory(self):
        eng = ChatEngine(self.cfg, self.db)
        try:
            eng.respond("my name is Sara and I prefer Flask", session="t2")
        finally:
            eng.close()
        # Kill the model: point at a dead port -> offline fallback.
        self.cfg["base_url"] = "http://127.0.0.1:1"
        eng2 = ChatEngine(self.cfg, self.db)
        try:
            out = eng2.respond("what is my name?", session="t2")
            self.assertEqual(out["mode"], "offline")
            self.assertIn("Sara", out["reply"])
            out3 = eng2.respond("what do you know about me?", session="t2")
            self.assertIn("Flask", out3["reply"])
        finally:
            eng2.close()

    def test_feedback_and_forget(self):
        eng = ChatEngine(self.cfg, self.db)
        try:
            out = eng.respond("I love FastAPI", session="t3")
            self.assertTrue(eng.mem.rate(out["chat_id"], "good"))
            liked, _ = eng.mem.lessons()
            self.assertTrue(liked)
            self.assertEqual(eng.mem.stats()["good"], 1)
            facts = eng.mem.facts()
            self.assertTrue(facts)
            self.assertTrue(eng.mem.forget_fact(facts[0]["id"]))
            self.assertFalse(eng.mem.forget_fact(999999))
        finally:
            eng.close()

    def test_recall_prefers_liked_answers(self):
        mem = ChatMemory(self.db)
        try:
            _, aid1 = mem.save_exchange("s", "flask routing question", "flask routing: short answer one")
            _, aid2 = mem.save_exchange("s", "flask routing question again", "flask routing: short answer two")
            mem.rate(aid2, "good")
            hits = mem.recall_chats("flask routing", k=2)
            self.assertTrue(hits)
            self.assertEqual(hits[0]["id"], aid2)  # liked answer floats to top
        finally:
            mem.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
