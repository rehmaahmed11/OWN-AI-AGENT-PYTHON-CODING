"""Self-learning chat engine: every chat is READ, LEARNED from, and used to TUNE the agent.

How it works (all local, pure standard library):

1. READ  — every user/assistant exchange is stored in SQLite (workspace/memory.db,
           new tables alongside the project-task memory).
2. LEARN — deterministic extractors pull durable facts out of your messages
           ("my name is Ahmed", "I prefer Flask", "remember that ...") into a
           `facts` table. 👍/👎 feedback is stored per reply.
3. TUNE  — before every reply the engine builds a *tuned* system prompt from:
             * your learned profile (facts),
             * the most relevant past chats (FTS5 recall, RAG-lite),
             * lessons from your feedback (do more of what you liked),
             * auto style-hints (e.g. user dislikes long answers -> be brief),
             * relevant past *project* memories (proven code patterns).
           So the agent literally behaves differently the more you chat.

If the model server is down it still works in OFFLINE mode: it answers from
what it already learned about you (name, likes, past chats) and keeps learning.
"""

from __future__ import annotations

import re
import sqlite3
import time
import uuid
from pathlib import Path

from . import llm
from .memory import Memory

_CHAT_SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    session TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL,
    content TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS chat_fts USING fts5(content);
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence INTEGER NOT NULL DEFAULT 1,
    source_chat_id INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    chat_id INTEGER NOT NULL,
    rating TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT ''
);
"""

# (fact_key, regex) — applied to every USER message. First group = value.
# "favorite" is special: group(1) becomes part of the key.
LEARN_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("name", re.compile(
        r"(?:my name is|my name'?s|call me)\s+([A-Za-z][A-Za-z .'\-]{1,40})", re.I)),
    ("role", re.compile(
        r"i (?:am a|am an|am the|'m a|'m an|work as a|work as an)\s+"
        r"([A-Za-z][A-Za-z .'\-]{1,40})", re.I)),
    ("likes", re.compile(r"i (?:like|love)\s+([^.!?\n]{2,80})", re.I)),
    ("prefers", re.compile(r"i prefer\s+([^.!?\n]{2,80})", re.I)),
    ("favorite", re.compile(
        r"my favou?rite\s+([A-Za-z]+)\s+is\s+([^.!?\n]{2,80})", re.I)),
    ("uses", re.compile(r"i (?:use|work with|code in)\s+([^.!?\n]{2,80})", re.I)),
    ("project", re.compile(
        r"i'?m (?:building|working on|making)\s+([^.!?\n]{2,80})", re.I)),
    ("note", re.compile(
        r"remember(?:\s+that)?\s*[:\-]?\s*([^.!?\n]{2,120})", re.I)),
]

_QA_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("name", re.compile(r"what(?:'s| is) my name|who am i\b", re.I)),
    ("role", re.compile(r"what (?:am i|do i do)\b", re.I)),
    ("likes", re.compile(r"what do i (?:like|love)\b", re.I)),
    ("prefers", re.compile(r"what do i prefer\b", re.I)),
    ("uses", re.compile(r"what do i use\b", re.I)),
    ("project", re.compile(r"what am i (?:building|working on|making)|what(?:'s| is) my project", re.I)),
    ("__profile__", re.compile(
        r"what do you know about me|tell me about yourself.*me|describe what you (?:know|learned) about me", re.I)),
]

_STOPWORDS = frozenset(
    "the a an and or but what when where which who why how is are was were be been "
    "being do does did will would can could should have has had with for from this that "
    "these those you your me my we our they them his her its not no yes please tell give "
    "make build create write code python".split()
)


def _clean_value(raw: str) -> str:
    v = re.sub(r"\s+", " ", raw).strip().strip(" .,:;!?\"'")
    # Drop trailing subordinate clauses that leak in ("... because ...").
    v = re.split(r"\s+(?:because|since|when|while|although)\s+", v, maxsplit=1)[0].strip()
    return v[:120]


_STOP_CONT = frozenset(
    "and but then when because since while with for who that which my i im".split())


def _clean_name(raw: str) -> str:
    """Keep the leading run of capitalized words ('Ahmed Khan'), max 3."""
    words = re.findall(r"[A-Za-z][a-z'\-]*", raw)
    out = []
    for w in words:
        if not re.fullmatch(r"[A-Z][a-z]+(?:'[a-z]+)?", w):
            break
        out.append(w)
        if len(out) >= 3:
            break
    if not out and words and words[0].lower() not in _STOP_CONT:
        out = [words[0].capitalize()]  # "my name is ahmed" (lowercase)
    return " ".join(out)[:60]


def _clean_role(raw: str) -> str:
    """Keep leading lowercase descriptor words ('software engineer'), max 4."""
    words = re.findall(r"[A-Za-z][a-z'\-]*", raw)
    out = []
    for i, w in enumerate(words):
        if w.lower() in _STOP_CONT or w.lower() in ("a", "an", "the"):
            break
        if i > 0 and w[0].isupper():
            break
        out.append(w.lower())
        if len(out) >= 4:
            break
    return " ".join(out)[:60]


def extract_facts(user_text: str) -> list[tuple[str, str]]:
    """Deterministically pull (key, value) learnings out of one user message."""
    found: list[tuple[str, str]] = []
    for key, rx in LEARN_PATTERNS:
        for m in rx.finditer(user_text):
            if key == "favorite":
                k = "favorite_" + re.sub(r"[^a-z]", "", m.group(1).lower())[:20]
                v = _clean_value(m.group(2))
            elif key == "name":
                k, v = key, _clean_name(m.group(1))
            elif key == "role":
                k, v = key, _clean_role(m.group(1))
            else:
                k, v = key, _clean_value(m.group(1))
            if len(v) >= 2 and "?" not in v:
                found.append((k, v))
    # de-dupe, keep order
    seen, out = set(), []
    for kv in found:
        if kv not in seen:
            seen.add(kv)
            out.append(kv)
    return out


class ChatMemory:
    """SQLite store for chats + learned facts + feedback. Shares memory.db."""

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(db_path), timeout=30)
        self.db.executescript(_CHAT_SCHEMA)

    def close(self) -> None:
        try:
            self.db.close()
        except Exception:
            pass

    # ---------------- chats ----------------
    def save_exchange(self, session: str, user_text: str, assistant_text: str) -> tuple[int, int]:
        ts = time.time()
        cur = self.db.execute(
            "INSERT INTO chats (ts, session, role, content) VALUES (?, ?, 'user', ?)",
            (ts, session, user_text),
        )
        uid = int(cur.lastrowid)
        self.db.execute("INSERT INTO chat_fts (rowid, content) VALUES (?, ?)", (uid, user_text))
        cur = self.db.execute(
            "INSERT INTO chats (ts, session, role, content) VALUES (?, ?, 'assistant', ?)",
            (ts, session, assistant_text),
        )
        aid = int(cur.lastrowid)
        self.db.execute("INSERT INTO chat_fts (rowid, content) VALUES (?, ?)", (aid, assistant_text))
        self.db.commit()
        return uid, aid

    def history(self, session: str = "", limit: int = 60) -> list[dict]:
        if session:
            rows = self.db.execute(
                "SELECT id, ts, role, content FROM chats WHERE session = ?"
                " ORDER BY id DESC LIMIT ?", (session, limit),
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT id, ts, role, content FROM chats ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        out = [{"id": i, "ts": ts, "role": r, "content": c} for i, ts, r, c in reversed(rows)]
        # attach feedback ratings
        if out:
            fb = self.db.execute(
                f"SELECT chat_id, rating FROM feedback WHERE chat_id IN "
                f"({','.join('?' * len(out))})", [m["id"] for m in out]
            ).fetchall()
            ratings = {cid: rating for cid, rating in fb}
            for m in out:
                if m["id"] in ratings:
                    m["rating"] = ratings[m["id"]]
        return out

    def recall_chats(self, query: str, k: int = 5) -> list[dict]:
        """FTS5 search over past chats. Good-rated answers sort first."""
        words = [w for w in re.findall(r"[A-Za-z0-9_]{3,}", query.lower())
                 if w not in _STOPWORDS][:8]
        if not words:
            return []
        match = " OR ".join(f'"{w}"' for w in words)
        try:
            rows = self.db.execute(
                "SELECT c.id, c.role, c.content,"
                " (SELECT rating FROM feedback f WHERE f.chat_id = c.id LIMIT 1) AS rating"
                " FROM chat_fts f JOIN chats c ON c.id = f.rowid"
                " WHERE chat_fts MATCH ? ORDER BY rank LIMIT ?",
                (match, k * 2),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        scored = []
        for cid, role, content, rating in rows:
            boost = 0
            if rating == "good":
                boost = 2
            elif rating == "bad":
                boost = -1
            scored.append((boost, {"id": cid, "role": role, "content": content, "rating": rating}))
        scored.sort(key=lambda t: -t[0])
        return [d for _, d in scored[:k]]

    # ---------------- facts (the durable learning) ----------------
    def learn(self, user_text: str, source_chat_id: int = 0) -> list[dict]:
        learned = []
        for key, value in extract_facts(user_text):
            row = self.db.execute(
                "SELECT id, confidence FROM facts WHERE key = ? AND value = ?",
                (key, value),
            ).fetchone()
            if row:
                self.db.execute(
                    "UPDATE facts SET confidence = confidence + 1, ts = ? WHERE id = ?",
                    (time.time(), row[0]),
                )
                learned.append({"id": row[0], "key": key, "value": value,
                                "confidence": row[1] + 1, "new": False})
            else:
                cur = self.db.execute(
                    "INSERT INTO facts (ts, key, value, confidence, source_chat_id)"
                    " VALUES (?, ?, ?, 1, ?)",
                    (time.time(), key, value, source_chat_id),
                )
                learned.append({"id": int(cur.lastrowid), "key": key, "value": value,
                                "confidence": 1, "new": True})
        self.db.commit()
        return learned

    def facts(self, limit: int = 100) -> list[dict]:
        rows = self.db.execute(
            "SELECT id, ts, key, value, confidence FROM facts ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [{"id": i, "ts": ts, "key": k, "value": v, "confidence": c}
                for i, ts, k, v, c in rows]

    def forget_fact(self, fact_id: int) -> bool:
        cur = self.db.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
        self.db.commit()
        return cur.rowcount > 0

    # ---------------- feedback ----------------
    def rate(self, chat_id: int, rating: str, note: str = "") -> bool:
        if rating not in ("good", "bad"):
            return False
        self.db.execute("DELETE FROM feedback WHERE chat_id = ?", (chat_id,))
        self.db.execute(
            "INSERT INTO feedback (ts, chat_id, rating, note) VALUES (?, ?, ?, ?)",
            (time.time(), chat_id, rating, note[:200]),
        )
        self.db.commit()
        return True

    def lessons(self, limit: int = 3) -> tuple[list[str], list[str]]:
        """(liked_snippets, disliked_snippets) — the tuning signal."""
        liked, disliked = [], []
        for rating, target in (("good", liked), ("bad", disliked)):
            rows = self.db.execute(
                "SELECT c.content FROM feedback f JOIN chats c ON c.id = f.chat_id"
                " WHERE f.rating = ? ORDER BY f.id DESC LIMIT ?",
                (rating, limit),
            ).fetchall()
            for (content,) in rows:
                target.append(content[:300])
        return liked, disliked

    # ---------------- stats + auto-tuning ----------------
    def stats(self) -> dict:
        chats = self.db.execute("SELECT COUNT(*) FROM chats").fetchone()[0]
        facts = self.db.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        good = self.db.execute("SELECT COUNT(*) FROM feedback WHERE rating='good'").fetchone()[0]
        bad = self.db.execute("SELECT COUNT(*) FROM feedback WHERE rating='bad'").fetchone()[0]
        avg_bad_len = self.db.execute(
            "SELECT AVG(LENGTH(c.content)) FROM feedback f JOIN chats c ON c.id = f.chat_id"
            " WHERE f.rating = 'bad'").fetchone()[0] or 0
        code_answers = self.db.execute(
            "SELECT COUNT(*) FROM chats WHERE role='assistant' AND content LIKE '%```%'"
        ).fetchone()[0]
        return {"chats": chats, "facts": facts, "good": good, "bad": bad,
                "avg_bad_len": avg_bad_len, "code_answers": code_answers}

    def top_topics(self, limit: int = 5) -> list[str]:
        rows = self.db.execute(
            "SELECT content FROM chats WHERE role='user' ORDER BY id DESC LIMIT 200"
        ).fetchall()
        freq: dict[str, int] = {}
        for (content,) in rows:
            for w in re.findall(r"[a-z]{4,}", content.lower()):
                if w not in _STOPWORDS:
                    freq[w] = freq.get(w, 0) + 1
        return sorted(freq, key=lambda w: -freq[w])[:limit]


def profile_text(facts: list[dict]) -> str:
    if not facts:
        return ""
    by_key: dict[str, list[str]] = {}
    for f in facts:
        by_key.setdefault(f["key"], [])
        if f["value"] not in by_key[f["key"]]:
            by_key[f["key"]].append(f["value"])
    lines = [f"- {k}: {'; '.join(v)}" for k, v in sorted(by_key.items())]
    return "Things you have learned about this user (use them to personalize):\n" + "\n".join(lines)


def style_hints(mem: ChatMemory) -> list[str]:
    """Auto-tuning rules derived from stats + feedback. This is the agent
    adjusting its own behaviour based on how you reacted."""
    s = mem.stats()
    hints = []
    if s["bad"] >= 2 and s["avg_bad_len"] > 600:
        hints.append("The user disliked several of your LONG answers — keep replies SHORT and direct.")
    if s["good"] >= 2:
        hints.append("The user 👍-rated answers before — match that style (check the liked examples).")
    topics = mem.top_topics()
    if topics:
        hints.append("The user often chats about: " + ", ".join(topics) + ".")
    if s["code_answers"] >= 3:
        hints.append("The user works with code a lot — include small runnable examples when relevant.")
    return hints


def tuned_system_prompt(mem: ChatMemory, project_mem: Memory, query: str, cfg: dict) -> tuple[str, list[dict]]:
    """Build the self-tuned system prompt for this one reply."""
    from . import prompts  # local import: avoids circulars

    facts = mem.facts()
    recalled = mem.recall_chats(query, k=cfg.get("chat_results", 5))
    project_snippets = project_mem.recall(query, k=2)
    liked, disliked = mem.lessons()

    parts = [prompts.SYSTEM_PROMPT]
    parts.append(
        "\nYou are chatting in the agent's GUI. Be warm, concise, and helpful. "
        "Remember: everything the user tells you is being learned, so acknowledge "
        "new personal details briefly when they appear."
    )
    prof = profile_text(facts)
    if prof:
        parts.append("\n" + prof)
    if recalled:
        lines = []
        for r in recalled:
            tag = "👍 liked" if r.get("rating") == "good" else ("👎 disliked" if r.get("rating") == "bad" else "past")
            lines.append(f"[{tag} {r['role']}]: {r['content'][:400]}")
        parts.append("\nRelevant past chats with this user (stay consistent with them):\n" + "\n---\n".join(lines))
    if project_snippets:
        parts.append("\nRelevant lessons from projects you built before:\n" + "\n---\n".join(project_snippets))
    if liked:
        parts.append("\nAnswers the user LIKED (imitate this style):\n- " + "\n- ".join(liked))
    if disliked:
        parts.append("\nAnswers the user DISLIKED (do NOT repeat this style):\n- " + "\n- ".join(disliked))
    hints = style_hints(mem)
    if hints:
        parts.append("\nSelf-tuning notes (derived from this user's reactions):\n- " + "\n- ".join(hints))
    return "\n".join(parts), recalled


def offline_reply(mem: ChatMemory, user_text: str) -> str:
    """Answer purely from learned memory when the model server is unreachable."""
    facts = mem.facts()
    by_key: dict[str, list[str]] = {}
    for f in facts:
        by_key.setdefault(f["key"], []).append(f["value"])
    for key, rx in _QA_PATTERNS:
        if rx.search(user_text):
            if key == "__profile__":
                if not facts:
                    return ("📴 The model server is offline, and I haven't learned anything "
                            "about you yet. Tell me things like “my name is …” or “I prefer …” "
                            "and I'll remember them. 🧠")
                lines = [f"• {k}: {'; '.join(v)}" for k, v in sorted(by_key.items())]
                return ("📴 Model server is offline, but here's what I've learned about you so far:\n"
                        + "\n".join(lines))
            if key in by_key:
                label = {"name": "Your name is", "role": "You are",
                         "likes": "You like", "prefers": "You prefer",
                         "uses": "You use", "project": "You're building"}.get(key, key)
                return "📴 (offline — answering from memory 🧠) {}: {}.".format(label, "; ".join(by_key[key]))
            return (f"📴 Model server is offline and I haven't learned your {key} yet. "
                    f"Tell me and I'll remember it! 🧠")
    recalled = mem.recall_chats(user_text, k=3)
    if recalled:
        bits = " | ".join(f"“{r['content'][:120]}”" for r in recalled)
        return ("📴 Model server is offline, so I'm answering from memory. 🧠 "
                f"This reminded me of: {bits}\n\nI've still saved and learned from your message — "
                "start the model (`bash start_model.sh`) for full answers.")
    return ("📴 Model server is offline. I've saved your message and learned from it 🧠 — "
            "start the model with `bash start_model.sh` and ask again for a full answer.")


class ChatEngine:
    """One-shot engine per request: holds the two memory handles."""

    def __init__(self, cfg: dict, db_path: Path):
        self.cfg = cfg
        self.mem = ChatMemory(db_path)
        self.projects = Memory(db_path)

    def close(self) -> None:
        self.mem.close()

    def respond(self, message: str, session: str = "default",
                history: list[dict] | None = None) -> dict:
        message = (message or "").strip()
        if not message:
            return {"reply": "Say something and I'll learn from it! 🧠",
                    "learned": [], "recalled": 0, "mode": "empty", "chat_id": 0}
        if len(message) > 4000:
            message = message[:4000]

        system, recalled = tuned_system_prompt(self.mem, self.projects, message, self.cfg)
        messages = [{"role": "system", "content": "[MODE:CHAT]\n" + system}]
        for h in (history or [])[-10:]:
            if h.get("role") in ("user", "assistant") and h.get("content"):
                messages.append({"role": h["role"], "content": h["content"][:2000]})
        messages.append({"role": "user", "content": message})

        try:
            reply = llm.chat(messages, self.cfg, max_tokens=self.cfg.get("max_tokens_chat", 512))
            mode = "llm"
        except llm.LLMError:
            reply = offline_reply(self.mem, message)
            mode = "offline"
        reply = (reply or "").strip() or "(empty reply — try again)"

        _, aid = self.mem.save_exchange(session, message, reply)
        learned = self.mem.learn(message, source_chat_id=aid)
        return {"reply": reply, "learned": learned, "recalled": len(recalled),
                "mode": mode, "chat_id": aid,
                "facts_count": len(self.mem.facts(limit=1000))}

    def new_session(self) -> str:
        return uuid.uuid4().hex[:8]
