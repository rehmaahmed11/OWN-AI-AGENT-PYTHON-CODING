"""A fake llama.cpp server for offline testing/demo.

Implements POST /v1/chat/completions and GET /health. Recognizes the
[MODE:...] tags in prompts.py and answers with canned but REAL content —
enough to run the full agent loop with zero model download.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PLAN = {
    "name": "shoes-company-site",
    "framework": "flask",
    "summary": "Flask website for a shoes company with all standard pages.",
    "features": [
        "Home page with hero section",
        "Products catalog page",
        "About Us page",
        "Contact Us page with form",
        "Shared base layout and CSS",
        "404 error page",
    ],
    "files": [
        {"path": "app.py", "purpose": "Flask app with all routes"},
        {"path": "templates/base.html", "purpose": "base layout with navbar"},
        {"path": "templates/index.html", "purpose": "home page"},
        {"path": "static/style.css", "purpose": "site styles"},
        {"path": "requirements.txt", "purpose": "python dependencies"},
        {"path": "README.md", "purpose": "how to run"},
    ],
}

APP_PY = '''from flask import Flask, render_template

app = Flask(__name__)

SHOES = [
    {"id": 1, "name": "Runner Pro", "price": 79.99},
    {"id": 2, "name": "Street Classic", "price": 59.99},
    {"id": 3, "name": "Trail Beast", "price": 99.99},
]


@app.route("/")
def index():
    return render_template("index.html", shoes=SHOES)


@app.route("/products")
def products():
    return render_template("products.html", shoes=SHOES)


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/contact", methods=["GET", "POST"])
def contact():
    return render_template("contact.html")


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
'''

CANNED = {
    "templates/base.html": ("html", "<!doctype html>\n<html><head>"
                            '<link rel="stylesheet" href="/static/style.css">'
                            "<title>{% block title %}ShoeCo{% endblock %}</title></head>\n"
                            "<body><nav><a href=\"/\">Home</a> | <a href=\"/products\">Products</a>"
                            " | <a href=\"/about\">About</a> | <a href=\"/contact\">Contact</a></nav>\n"
                            "{% block content %}{% endblock %}</body></html>\n"),
    "templates/index.html": ("html", '{% extends "base.html" %}\n{% block content %}'
                             "<h1>Welcome to ShoeCo</h1>{% endblock %}\n"),
    "static/style.css": ("css", "body { font-family: sans-serif; margin: 2rem; }\n"
                         "nav a { margin-right: .5rem; }\n"),
    "requirements.txt": ("txt", "flask>=3.0\n"),
    "README.md": ("md", "# ShoeCo Website\n\n```bash\npip install -r requirements.txt\n"
                  "python app.py\n# open http://127.0.0.1:5000\n```\n"),
}


def write_answer(path: str) -> str:
    if path == "app.py":
        lang, code = "python", APP_PY
    else:
        lang, code = CANNED.get(path, ("txt", f"# generated placeholder for {path}\n"))
    return f"```{lang}\n{code}```"


class MockHandler(BaseHTTPRequestHandler):
    def _send(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/health", "/v1/models"):
            self._send({"status": "ok", "data": []})
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self._send({"error": "not found"}, 404)
            return
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        text = "\n".join(m.get("content", "") for m in payload["messages"])
        if "[MODE:PLAN]" in text:
            # Emulate a real model: prose around the JSON.
            content = "Here is my plan:\n" + json.dumps(PLAN, indent=2) + "\nHope that helps."
        elif "[MODE:WRITE path=" in text:
            path = text.split("[MODE:WRITE path=", 1)[1].split("]", 1)[0]
            content = write_answer(path)
        elif "[MODE:REVIEW]" in text:
            # templates/products.html, about.html, contact.html, 404.html are
            # referenced by app.py — a real small model would often notice:
            self._reply('{"missing": []}')
            return
        elif "[MODE:CHAT]" in text:
            last_user = ""
            for m in reversed(payload["messages"]):
                if m.get("role") == "user":
                    last_user = m.get("content", "")
                    break
            # Echo what "profile" the tuned prompt carried, so tests can prove
            # learning flows into the prompt.
            learned = "nothing yet"
            if "Things you have learned about this user" in text:
                prof = text.split("Things you have learned about this user", 1)[1]
                learned = prof.split("Relevant past chats")[0].strip()[:300]
            content = (f"(mock) I heard you: {last_user[:160]}\n"
                       f"What I know about you so far: {learned}")
            self._reply(content)
            return
        else:
            content = "I do not understand."
        self._reply(content)

    def _reply(self, content):
        self._send({"choices": [{"message": {"role": "assistant", "content": content}}]})

    def log_message(self, *a):  # quiet
        pass


def serve(port: int = 0) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), MockHandler)
    return server


if __name__ == "__main__":
    s = serve(8123)
    print("Mock model on http://127.0.0.1:8123")
    s.serve_forever()
