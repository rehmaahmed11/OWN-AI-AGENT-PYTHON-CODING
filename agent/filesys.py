"""Safe file access — the ONLY way the agent touches your disk.

Guarantees:
  * Writes can only land inside approved roots (the workspace by default,
    plus anything you add to "extra_roots" in agent_config.json).
  * Path traversal ("../..", absolute paths) is rejected.
  * There is intentionally NO delete/move function in this module.
    The agent can create and overwrite files inside approved roots — nothing
    else, ever.
"""

from __future__ import annotations

from pathlib import Path

from .config import REPO_ROOT


class UnsafePathError(RuntimeError):
    pass


class Workspace:
    def __init__(self, cfg: dict):
        ws = cfg.get("workspace", "workspace")
        ws_path = Path(ws)
        if not ws_path.is_absolute():
            ws_path = REPO_ROOT / ws
        self.roots: dict[str, Path] = {"workspace": ws_path.resolve()}
        self.roots["workspace"].mkdir(parents=True, exist_ok=True)
        for name, path in (cfg.get("extra_roots") or {}).items():
            p = Path(path)
            if p.is_dir():
                self.roots[name] = p.resolve()

    def available_roots(self) -> list[str]:
        return sorted(self.roots)

    def resolve(self, root_name: str, rel: str) -> Path:
        if root_name not in self.roots:
            raise UnsafePathError(
                f"Root '{root_name}' is not approved. "
                f"Available roots: {', '.join(self.available_roots())}"
            )
        rel = rel.strip()
        if rel.startswith("/") or rel.startswith("~") or ":" in rel[:2]:
            raise UnsafePathError(f"Refusing absolute/home path: {rel!r}")
        if not rel or rel.startswith("..") or "/../" in rel or rel.endswith("/.."):
            raise UnsafePathError(f"Refusing path traversal: {rel!r}")
        root = self.roots[root_name]
        target = (root / rel).resolve()
        if target != root and root not in target.parents:
            raise UnsafePathError(f"Path escapes approved root: {rel!r}")
        return target

    def write_text(self, root_name: str, rel: str, content: str) -> Path:
        """Create/overwrite a file inside an approved root. Returns its path."""
        target = self.resolve(root_name, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def exists_nonempty(self, root_name: str, rel: str) -> bool:
        try:
            p = self.resolve(root_name, rel)
        except UnsafePathError:
            return False
        return p.is_file() and p.stat().st_size > 0

    def tree(self, root_name: str, sub: str = "") -> list[str]:
        """Human-readable listing: 'path (123 B)' lines, sorted."""
        base = self.resolve(root_name, sub or ".")
        if base.is_file():
            return [f"{base.name} ({base.stat().st_size} B)"]
        lines = []
        for p in sorted(base.rglob("*")):
            if p.is_file():
                lines.append(f"{p.relative_to(base)} ({p.stat().st_size} B)")
        return lines
