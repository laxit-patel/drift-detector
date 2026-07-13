"""Local-folder SourceProvider: scan a directory of git repos on disk. No token, no network.
Implements the same five read methods as GitLabClient (the SourceProvider seam)."""
from __future__ import annotations

from pathlib import Path

_SKIP_DIRS = {".git", "node_modules", "vendor", ".venv", "dist", "build", "target", "__pycache__"}
_MAX_BYTES = 1_000_000


class LocalProvider:
    def __init__(self, root: str, *, run=None):
        self.root = Path(root)
        self._run = run                     # git runner, wired in Task 2
        repos = sorted(d for d in self.root.iterdir()
                       if d.is_dir() and (d / ".git").exists())
        self.projects = [(i + 1, d.name, d) for i, d in enumerate(repos)]
        self._by_id = {pid: abs_ for pid, _rel, abs_ in self.projects}

    def _repo_path(self, project_id: int) -> Path:
        return self._by_id[project_id]

    def _walk_files(self, base: Path):
        for p in base.rglob("*"):
            if p.is_dir():
                continue
            if any(part in _SKIP_DIRS for part in p.relative_to(base).parts):
                continue
            yield p

    def get_tree(self, project_id: int, ref: str) -> list:
        base = self._repo_path(project_id)
        return [str(p.relative_to(base)) for p in self._walk_files(base)]

    def get_raw_file(self, project_id: int, path: str, ref: str) -> "str | None":
        f = self._repo_path(project_id) / path
        try:
            return f.read_text(encoding="utf-8")
        except (FileNotFoundError, IsADirectoryError, UnicodeDecodeError, OSError):
            return None

    def search_blobs(self, project_id: int, query: str) -> list:
        base = self._repo_path(project_id)
        hits = []
        for p in self._walk_files(base):
            try:
                if p.stat().st_size > _MAX_BYTES:
                    continue
                if query in p.read_text(encoding="utf-8"):
                    hits.append({"path": str(p.relative_to(base))})
            except (UnicodeDecodeError, OSError):
                continue
        return hits
