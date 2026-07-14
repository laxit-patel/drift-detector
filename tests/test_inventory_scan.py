import json
import subprocess
from pathlib import Path
from agent.inventory_scan import scan_folder


def _git_init(d, files):
    d.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                    "--allow-empty", "-q", "-am", "init"], cwd=d, check=True)


def _canned_stripe(path):
    return json.dumps({"results": [
        {"check_id": "x.stripe-endpoint", "path": path, "start": {"line": 1},
         "extra": {"metadata": {"vendor": "Stripe", "techKey": "api:stripe", "kind": "endpoint"}}}],
        "errors": [], "paths": {"scanned": [path]}})


def test_scan_folder_end_to_end(tmp_path):
    root = tmp_path / "repos"
    _git_init(root / "web", {"composer.json": '{"require": {"php": "^8.2"}}',
                             "pay.php": '"https://api.stripe.com/v1/x";\n'})
    state = tmp_path / "state"
    out = scan_folder(str(root), str(state), "2026-07-14",
                      engine="semgrep", run=lambda args: _canned_stripe("pay.php"))
    doc = out["doc"]
    assert doc["scope"]["reposScanned"] == 1
    repo = doc["repos"][0]
    assert repo["path"] == "web" and repo["runtimes"]["php"]["range"] == "^8.2"
    assert repo["endpoints"][0]["techKey"] == "api:stripe"
    assert doc["unique_apis"] == ["Stripe"]
    assert (state / "inventory.json").exists()                 # IR persisted
    assert "Stripe" in out["report_md"]


def test_scan_folder_incremental_cache_reused(tmp_path):
    root = tmp_path / "repos"
    _git_init(root / "web", {"composer.json": '{"require": {"php": "^8.2"}}'})
    state = tmp_path / "state"
    calls = {"n": 0}

    def counting_run(args):
        calls["n"] += 1
        return json.dumps({"results": [], "errors": [], "paths": {"scanned": []}})

    scan_folder(str(root), str(state), "2026-07-14", engine="semgrep", run=counting_run)
    assert calls["n"] == 1                                      # scanned once
    scan_folder(str(root), str(state), "2026-07-21", engine="semgrep", run=counting_run)
    assert calls["n"] == 1                                      # unchanged sha -> cache hit, engine NOT re-run


from agent import cli


def test_cli_inventory_scan_writes_json_and_md(tmp_path, monkeypatch):
    root = tmp_path / "repos"
    _git_init(root / "web", {"composer.json": '{"require": {"php": "^8.2"}}',
                             "pay.php": '"https://api.stripe.com/v1/x";\n'})
    # stub the engine so no real binary is needed
    import agent.inventory_scan as inv
    monkeypatch.setattr(inv.scan_util, "resolve_engine", lambda engine="opengrep": "semgrep")
    monkeypatch.setattr(inv.opengrep, "_default_run", lambda args: _canned_stripe("pay.php"), raising=False)

    out_json = tmp_path / "inv.json"
    out_md = tmp_path / "INVENTORY.md"
    rc = cli.main(["inventory-scan", "--root", str(root), "--state", str(tmp_path / "state"),
                   "--out-json", str(out_json), "--out-md", str(out_md), "--now", "2026-07-14"])
    assert rc == 0
    doc = json.loads(out_json.read_text())
    assert doc["repos"][0]["path"] == "web" and doc["unique_apis"] == ["Stripe"]
    assert "Stripe" in out_md.read_text()
