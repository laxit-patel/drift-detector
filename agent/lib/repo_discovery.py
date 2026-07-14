"""Multi-root, recursive git-repo discovery for the Drift Detector inventory scanner.

Pure filesystem discovery (pathlib only, no git subprocess): a directory "is a repo"
iff it contains a `.git` entry. Discovery does not descend into a found repo (its
submodules/vendored `.git` dirs are not separate repos to scan) nor into common
noise directories (`_SKIP_DIRS`).
"""
from __future__ import annotations

from pathlib import Path

_SKIP_DIRS = {".git", "node_modules", "vendor", ".venv", "dist", "build", "target", "__pycache__"}


def _find_git_repos(root: Path):
    """Yield each dir under (and including) root that is a git repo, recursively.

    A repo is a dir containing a `.git` entry. Once found, its subtree is not
    descended into. Dirs named in `_SKIP_DIRS` are never descended into.
    """
    if (root / ".git").exists():
        yield root
        return
    try:
        children = sorted(d for d in root.iterdir() if d.is_dir())
    except OSError:
        return
    for child in children:
        if child.name in _SKIP_DIRS:
            continue
        yield from _find_git_repos(child)


def discover_repos(roots: list) -> list:
    """Find all git repos recursively beneath each of `roots`.

    Returns a sorted list of (abs_repo_path, identity) tuples, deduped by
    resolved absolute repo path. `identity` is the repo's path relative to
    the root it was discovered under (or the root's basename, if the repo
    IS that root). If two different repos would otherwise share the same
    identity string, both are disambiguated by prefixing with their own
    root's basename: `<root_basename>/<identity>`.
    """
    # seen: resolved abs path -> identity (first root that reaches it wins the entry)
    seen: dict = {}

    for raw_root in roots:
        root = Path(raw_root).resolve()
        for repo in _find_git_repos(root):
            repo_resolved = repo.resolve()
            if repo_resolved in seen:
                continue
            if repo_resolved == root:
                identity = root.name
            else:
                identity = repo_resolved.relative_to(root).as_posix()
            seen[repo_resolved] = (root.name, identity)

    # Detect identity collisions across different resolved paths.
    identity_owners: dict = {}
    for repo_resolved, (root_name, identity) in seen.items():
        identity_owners.setdefault(identity, set()).add(repo_resolved)

    result = []
    for repo_resolved, (root_name, identity) in seen.items():
        if len(identity_owners[identity]) > 1:
            identity = f"{root_name}/{identity}"
        result.append((str(repo_resolved), identity))

    return sorted(result)
