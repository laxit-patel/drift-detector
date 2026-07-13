from agent.lib.models import ChangeEntry
from agent.lib import kb_store
from agent import run as run_mod

class _Delivery:
    actions = ["chat-alert"]
class _Cfg:
    kb_root = None
    delivery = _Delivery()
    class delivery_cfg: pass

def _cfg(kb_root):
    c = _Cfg(); c.kb_root = kb_root; return c

INV = {"records": [{"repo": "c/a", "tech_key": "runtime:php", "kind": "runtime",
                    "version_hint": "8.0", "declared_range": "", "ecosystem": "docker"}],
       "usedTechs": [], "coverage": {"reposScanned": 1}}
ACTIVE = {"active": [{"id": 42, "path_with_namespace": "c/a"}]}

def test_run_pipeline_lifecycle_action(tmp_path):
    root = str(tmp_path)
    kb_store.append_entries(root, "runtime:php", [ChangeEntry(
        techKey="runtime:php", date="2023-11-26", changeType="deprecation", title="PHP 8.0 EOL",
        summary="", sourceUrl="https://eol", sourceTier=1, evidence="PHP 8.0 EOL", affectedArea="cycle 8.0")])
    out = run_mod.run_pipeline(inventory=INV, active=ACTIVE, kb_root=root, prev_doc={},
                               config=_cfg(root), now="2026-07-13",
                               classify_fn=lambda items: [], fetched_urls={"https://eol"})
    doc = out["doc"]
    assert doc["counts"]["action"] == 1                # passed EOL, evidence present, url fetched -> kept
    assert "Business-logic risk" in out["report_md"]

def test_run_pipeline_hallucinated_url_becomes_gap(tmp_path):
    root = str(tmp_path)
    kb_store.append_entries(root, "runtime:php", [ChangeEntry(
        techKey="runtime:php", date="2023-11-26", changeType="deprecation", title="PHP 8.0 EOL",
        summary="", sourceUrl="https://eol", sourceTier=1, evidence="PHP 8.0 EOL", affectedArea="cycle 8.0")])
    out = run_mod.run_pipeline(inventory=INV, active=ACTIVE, kb_root=root, prev_doc={},
                               config=_cfg(root), now="2026-07-13",
                               classify_fn=lambda items: [], fetched_urls=set())   # nothing fetched
    assert out["doc"]["counts"]["action"] == 0
    assert out["doc"]["coverage"]["classifyGaps"]      # rejected -> coverage gap, not silently kept

def test_deliver_runs_only_configured_actions():
    posted = []
    res = run_mod.deliver({"x": 1}, "md", _cfg("x"),
                          commit=lambda ctx: "cid", chat=lambda ctx: posted.append(1) or True)
    names = {r["name"]: r["ok"] for r in res}
    assert names.get("chat-alert") is True and "commit-report" not in names   # commit not in config.actions
