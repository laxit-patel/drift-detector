from agent.lib.local_provider import LocalProvider

def _make_repo(root, name, files):
    d = root / name
    (d / ".git").mkdir(parents=True)          # marks it a repo
    for rel, content in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d

def test_discovers_git_repos_and_ids(tmp_path):
    _make_repo(tmp_path, "acme", {"package.json": "{}"})
    _make_repo(tmp_path, "beta", {"composer.json": "{}"})
    (tmp_path / "not-a-repo").mkdir()          # no .git -> ignored
    p = LocalProvider(str(tmp_path))
    paths = sorted(rel for _id, rel, _abs in p.projects)
    assert paths == ["acme", "beta"]
    assert all(isinstance(i, int) for i, _, _ in p.projects)

def test_get_tree_skips_junk(tmp_path):
    _make_repo(tmp_path, "acme", {"package.json": "{}", "src/app.js": "x",
                                  "node_modules/dep/i.js": "y"})
    p = LocalProvider(str(tmp_path))
    pid = p.projects[0][0]
    tree = set(p.get_tree(pid, "main"))
    assert "package.json" in tree and "src/app.js" in tree
    assert not any("node_modules" in t for t in tree)

def test_get_raw_file(tmp_path):
    _make_repo(tmp_path, "acme", {"package.json": '{"name":"acme"}'})
    p = LocalProvider(str(tmp_path)); pid = p.projects[0][0]
    assert p.get_raw_file(pid, "package.json", "main") == '{"name":"acme"}'
    assert p.get_raw_file(pid, "missing.txt", "main") is None

def test_search_blobs_substring(tmp_path):
    _make_repo(tmp_path, "acme", {"src/Amazon.php": "use sellingpartnerapi client",
                                  "README.md": "nothing here"})
    p = LocalProvider(str(tmp_path)); pid = p.projects[0][0]
    hits = p.search_blobs(pid, "sellingpartnerapi")
    assert len(hits) == 1 and hits[0]["path"] == "src/Amazon.php"
    assert p.search_blobs(pid, "nonexistent") == []
