from pathlib import Path

from agent.lib.repo_discovery import discover_repos


def _mkrepo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()


def test_finds_immediate_and_nested_repos(tmp_path):
    root = tmp_path / "root"
    _mkrepo(root / "a")
    _mkrepo(root / "group" / "b")
    _mkrepo(root / "group" / "sub" / "c")

    found = discover_repos([str(root)])
    identities = sorted(identity for _, identity in found)
    assert identities == ["a", "group/b", "group/sub/c"]


def test_does_not_descend_into_a_found_repo(tmp_path):
    root = tmp_path / "root"
    _mkrepo(root / "a")
    _mkrepo(root / "a" / "vendored")

    found = discover_repos([str(root)])
    assert len(found) == 1
    abs_path, identity = found[0]
    assert identity == "a"
    assert Path(abs_path) == (root / "a").resolve()


def test_skips_node_modules_and_vendor(tmp_path):
    root = tmp_path / "root"
    _mkrepo(root / "node_modules" / "pkg")
    _mkrepo(root / "vendor" / "lib")

    found = discover_repos([str(root)])
    assert found == []


def test_multiple_roots_combined(tmp_path):
    root1 = tmp_path / "root1"
    root2 = tmp_path / "root2"
    _mkrepo(root1 / "a")
    _mkrepo(root1 / "group" / "b")
    _mkrepo(root2 / "x")
    _mkrepo(root2 / "group" / "y")

    found = discover_repos([str(root1), str(root2)])
    identities = sorted(identity for _, identity in found)
    assert identities == ["a", "group/b", "group/y", "x"]


def test_dedup_same_repo_via_two_roots(tmp_path):
    root1 = tmp_path / "root1"
    _mkrepo(root1 / "sub" / "repo")
    root2 = root1 / "sub"  # root2 is a plain subdir of root1; same repo reachable via both roots

    found = discover_repos([str(root1), str(root2)])
    assert len(found) == 1
    abs_path, _identity = found[0]
    assert Path(abs_path) == (root1 / "sub" / "repo").resolve()


def test_identity_collision_disambiguated(tmp_path):
    root1 = tmp_path / "root1"
    root2 = tmp_path / "root2"
    _mkrepo(root1 / "app")
    _mkrepo(root2 / "app")

    found = discover_repos([str(root1), str(root2)])
    identities = sorted(identity for _, identity in found)
    assert identities == ["root1/app", "root2/app"]


def test_root_itself_is_a_repo(tmp_path):
    root = tmp_path / "myrepo"
    _mkrepo(root)

    found = discover_repos([str(root)])
    assert len(found) == 1
    abs_path, identity = found[0]
    assert identity == "myrepo"
    assert Path(abs_path) == root.resolve()
