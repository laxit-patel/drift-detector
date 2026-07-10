# tests/test_candidates.py
from agent.lib.models import ChangeEntry
from agent.lib import kb_store
from agent import candidates

def _seed_kb(root, techkey, entries):
    kb_store.append_entries(root, techkey, entries)

def _ce(techkey, date, ctype, title):
    return ChangeEntry(techKey=techkey, date=date, changeType=ctype, title=title,
                       summary="", sourceUrl="https://x", sourceTier=1)

INV = {
    "records": [
        {"repo": "c/a", "tech_key": "runtime:php", "kind": "runtime", "version_hint": "8.0", "declared_range": "", "ecosystem": "docker"},
        {"repo": "c/a", "tech_key": "lib:npm/stripe", "kind": "library", "declared_range": "^12", "version_hint": "", "ecosystem": "npm"},
    ],
    "usedTechs": [{"repo": "c/a", "tech_key": "api:amazon-sp-api", "evidence": "x"}],
}
REPO_IDS = {"c/a": 42}

def test_techkeys_in_use_covers_records_and_used():
    m = candidates.techkeys_in_use(INV)
    assert "runtime:php" in m and "lib:npm/stripe" in m and "api:amazon-sp-api" in m
    assert m["api:amazon-sp-api"][0]["category"] == "integration"
    assert m["runtime:php"][0]["versionInUse"] == "8.0"

def test_build_candidates_joins_drift(tmp_path):
    root = str(tmp_path)
    _seed_kb(root, "runtime:php", [_ce("runtime:php", "2025-01-01", "eol", "PHP 8.0 EOL")])
    _seed_kb(root, "lib:npm/stripe", [])   # no drift
    cands = candidates.build_candidates(INV, root, {}, repo_ids=REPO_IDS)
    php = [c for c in cands if c["techKey"] == "runtime:php"]
    assert len(php) == 1
    assert php[0]["projectId"] == 42 and php[0]["repo"] == "c/a"
    assert php[0]["changeEntry"]["changeType"] == "eol"
    assert not any(c["techKey"] == "lib:npm/stripe" for c in cands)   # no drift -> no candidate

def test_build_candidates_respects_watermark(tmp_path):
    root = str(tmp_path)
    _seed_kb(root, "runtime:php", [_ce("runtime:php", "2025-01-01", "eol", "old")])
    cands = candidates.build_candidates(INV, root, {"runtime:php": "2025-06-01"}, repo_ids=REPO_IDS)
    assert cands == []    # entry older than watermark
