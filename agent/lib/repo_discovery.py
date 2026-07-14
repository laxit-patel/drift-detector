"""Multi-root, recursive git-repo discovery for the Drift Detector inventory scanner.

Pure filesystem discovery (pathlib only, no git subprocess): a directory "is a repo"
iff it contains a `.git` entry. Discovery does not descend into a found repo (its
submodules/vendored `.git` dirs are not separate repos to scan) nor into common
noise directories (`_SKIP_DIRS`).

Repo *identity* (the diff/tracking key) is derived deterministically and
independently of the order of `roots`:
- each repo's "home root" is the nearest ancestor root (longest path prefix);
- the base identity is the repo's path relative to that home root (or the home
  root's basename when the repo *is* the root);
- if two *different* repos would collide on the same identity (e.g. two roots
  that share a basename), each is disambiguated by prefixing with its home
  root's path relative to the common ancestor of all roots — unique by
  construction, since distinct absolute paths stay distinct relative to a shared
  prefix.
"""
from __future__ import annotations

import os
from pathlib import Path

_SKIP_DIRS = {".git", "node_modules", "vendor", ".venv", "dist", "build", "target", "__pycache__"}


def _find_git_repos(root: Path, visited: set | None = None):
    """Yield each dir under (and including) root that is a git repo, recursively.

    A repo is a dir containing a `.git` entry. Once found, its subtree is not
    descended into. Dirs named in `_SKIP_DIRS` are never descended into.
    Symlinks are followed, but a `visited` set of resolved paths guards against
    symlink cycles causing unbounded recursion.
    """
    if visited is None:
        visited = set()
    resolved = root.resolve()
    if resolved in visited:
        return
    visited.add(resolved)

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
        yield from _find_git_repos(child, visited)


def discover_repos(roots: list) -> list:
    """Find all git repos recursively beneath each of `roots`.

    Returns a sorted list of (abs_repo_path, identity) tuples, deduped by
    resolved absolute repo path. Identity is order-independent and
    collision-free — see the module docstring for the scheme.
    """
    resolved_roots = [Path(r).resolve() for r in roots]

    # Collect distinct repos by resolved absolute path.
    repos: set = set()
    for root in resolved_roots:
        for repo in _find_git_repos(root):
            repos.add(repo.resolve())

    # Home root = nearest ancestor root (longest path); deterministic, and
    # independent of the order of `roots`. Every discovered repo has at least
    # one ancestor (or equal) root, so `candidates` is never empty.
    def _home_root(repo: Path) -> Path:
        candidates = [r for r in resolved_roots if r == repo or r in repo.parents]
        return max(candidates, key=lambda r: (len(r.parts), str(r)))

    base: dict = {}
    for repo in repos:
        hr = _home_root(repo)
        identity = hr.name if repo == hr else repo.relative_to(hr).as_posix()
        base[repo] = (hr, identity)

    # Identity collisions can only occur across *different* home roots (distinct
    # repos under one root have distinct relative paths). Prefix colliding repos
    # with their home root's path relative to the common ancestor of all roots.
    owners: dict = {}
    for repo, (hr, identity) in base.items():
        owners.setdefault(identity, []).append(repo)

    def _disambig_prefix(hr: Path) -> str:
        try:
            common = Path(os.path.commonpath([str(r) for r in resolved_roots]))
            return hr.relative_to(common).as_posix()
        except ValueError:  # no common path (e.g. different drives) -> full path
            return hr.relative_to(hr.anchor).as_posix()

    result = []
    for repo, (hr, identity) in base.items():
        if len(owners[identity]) > 1:
            identity = f"{_disambig_prefix(hr)}/{identity}"
        result.append((str(repo), identity))

    return sorted(result)
