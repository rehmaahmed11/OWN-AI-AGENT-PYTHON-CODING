"""End-to-end test of the agent loop using the mock model server (offline).

Run:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import ast
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import planner
from agent.config import DEFAULTS
from agent.filesys import UnsafePathError, Workspace
from agent.memory import Memory
from tests.mock_llm import serve


class AgentLoopTest(unittest.TestCase):
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
        self.tmp = Path(tempfile.mkdtemp(prefix="agent-test-"))
        self.cfg = dict(DEFAULTS)
        self.cfg["base_url"] = f"http://127.0.0.1:{self.port}"
        self.cfg["workspace"] = str(self.tmp / "workspace")
        self.cfg["timeout_s"] = 10

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_full_task_shoe_company(self):
        logs: list[str] = []
        report = planner.run_task(
            "Make a Flask website for a shoes company", self.cfg, log=logs.append
        )
        root = self.tmp / "workspace"
        project = root / report["project_dir"]

        # Plan was honored: every planned file was written, non-empty.
        self.assertEqual(report["project_dir"], "shoes-company-site")
        self.assertGreaterEqual(len(report["written"]), 6)
        for rel in report["written"]:
            self.assertTrue((root / rel).is_file(), rel)
            self.assertGreater((root / rel).stat().st_size, 0, rel)

        # The generated Flask app is valid Python and has the standard pages.
        app_src = (project / "app.py").read_text()
        ast.parse(app_src)
        for route in ('"/"', "/products", "/about", "/contact"):
            self.assertIn(route, app_src)

        # Loop stayed quiet in the logs but covered all four phases.
        joined = "\n".join(logs)
        for phase in ("PLAN", "BUILD", "VERIFY", "MEMORY"):
            self.assertIn(phase, joined)

        # Memory learned the task and can recall it.
        mem = Memory(root / "memory.db")
        self.assertEqual(mem.count(), 1)
        self.assertTrue(mem.recall("flask shoes website"))
        self.assertTrue(mem.recall("contact page flask"))

    def test_path_safety(self):
        ws = Workspace(self.cfg)
        with self.assertRaises(UnsafePathError):
            ws.write_text("workspace", "../evil.txt", "nope")
        with self.assertRaises(UnsafePathError):
            ws.write_text("workspace", "/etc/passwd", "nope")
        with self.assertRaises(UnsafePathError):
            ws.write_text("shared", "x.txt", "nope")  # root not approved
        # Overwrite inside workspace is allowed:
        ws.write_text("workspace", "a/b.txt", "1")
        ws.write_text("workspace", "a/b.txt", "2")
        self.assertIn("a/b.txt", "\n".join(ws.tree("workspace")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
