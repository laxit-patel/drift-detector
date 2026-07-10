# tests/test_cli.py
import textwrap
from agent import cli


def _cfg(tmp_path):
    root = tmp_path / "kb"
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(f"""
        kb: {{ root: {root} }}
        feeds:
          - {{ techKey: runtime:php, label: PHP, category: runtime, adapter: endoflife, url: php, tier: 1 }}
    """))
    return str(p)


class _FakeResp:
    def __init__(self, payload):
        self._p = payload
    def raise_for_status(self):
        pass
    def json(self):
        return self._p


def test_cli_ingest_then_drift(tmp_path, monkeypatch, capsys):
    # Inject endoflife HTTP at call time by patching requests.get inside the adapter module,
    # so no production test-hook is needed and no network is touched.
    from agent.lib.feeds import endoflife
    payload = [{"cycle": "8.2", "eol": "2025-12-08"}]
    monkeypatch.setattr(endoflife.requests, "get", lambda *a, **k: _FakeResp(payload))

    cfg = _cfg(tmp_path)

    rc = cli.main(["ingest", "--config", cfg, "--now", "2026-07-05"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "runtime:php" in out and "1 new" in out

    rc = cli.main(["drift", "--config", cfg, "--since", "2025-01-01"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "PHP 8.2 end-of-life" in out
