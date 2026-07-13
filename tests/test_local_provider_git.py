from agent.lib.local_provider import LocalProvider

def _make_repo(root, name):
    (root / name / ".git").mkdir(parents=True)
    (root / name / "f.txt").write_text("x")
    return root / name

class FakeGit:
    """Scripts git output by matching a substring of the joined command."""
    def __init__(self, rules): self.rules = rules; self.calls = []
    def __call__(self, args):
        joined = " ".join(args); self.calls.append(joined)
        for key, out in self.rules.items():
            if key in joined:
                return out
        return ""

def test_list_candidate_projects(tmp_path):
    _make_repo(tmp_path, "acme")
    run = FakeGit({"rev-parse --abbrev-ref HEAD": "main",
                   "log -1 --format=%cI": "2026-07-01T10:00:00+00:00"})
    p = LocalProvider(str(tmp_path), run=run)
    got = p.list_candidate_projects("2026-04-14")
    assert got[0]["path_with_namespace"] == "acme"
    assert got[0]["default_branch"] == "main"
    assert got[0]["last_activity_at"].startswith("2026-07-01")
    assert isinstance(got[0]["id"], int)

def test_has_commit_since_returns_date_or_none(tmp_path):
    _make_repo(tmp_path, "acme")
    p1 = LocalProvider(str(tmp_path), run=FakeGit({"--since": "2026-06-20T00:00:00+00:00"}))
    pid = p1.projects[0][0]
    assert p1.has_commit_since(pid, "2026-04-14").startswith("2026-06-20")
    p2 = LocalProvider(str(tmp_path), run=FakeGit({}))   # empty -> no commit in window
    assert p2.has_commit_since(p2.projects[0][0], "2026-04-14") is None
