from agent import commit_report

class FakeClient:
    def __init__(self, existing):  # set of existing paths
        self.existing = existing; self.committed = None
    def get_raw_file(self, pid, path, ref):
        return "old" if path in self.existing else None
    def create_commit(self, pid, branch, message, actions):
        self.committed = actions; return {"id": "c1"}

def test_commit_files_picks_create_vs_update():
    client = FakeClient(existing={"state/findings.json"})
    cid = commit_report.commit_files(client, 9, "main", "weekly",
              {"reports/r.md": "REPORT", "state/findings.json": "{}"}, "main")
    assert cid == "c1"
    by_path = {a["file_path"]: a["action"] for a in client.committed}
    assert by_path["reports/r.md"] == "create"          # new file
    assert by_path["state/findings.json"] == "update"    # existing file
