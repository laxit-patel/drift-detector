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
    _seed_kb(root, "runtime:php", [_ce("runtime:php", "2025-01-01", "deprecation", "PHP 8.0 EOL")])
    _seed_kb(root, "lib:npm/stripe", [])   # no drift
    cands = candidates.build_candidates(INV, root, repo_ids=REPO_IDS)
    php = [c for c in cands if c["techKey"] == "runtime:php"]
    assert len(php) == 1
    assert php[0]["projectId"] == 42 and php[0]["repo"] == "c/a"
    assert php[0]["changeEntry"]["changeType"] == "deprecation"
    assert not any(c["techKey"] == "lib:npm/stripe" for c in cands)   # no drift -> no candidate

def test_lifecycle_entry_version_matched_to_cycle(tmp_path):
    root = str(tmp_path)
    kb_store.append_entries(root, "runtime:php", [ChangeEntry(
        techKey="runtime:php", date="2023-11-26", changeType="deprecation", title="PHP 8.0 EOL",
        summary="", sourceUrl="https://x", sourceTier=1, affectedArea="cycle 8.0")])
    inv_80 = {"records": [{"repo": "c/a", "tech_key": "runtime:php", "kind": "runtime", "version_hint": "8.0", "declared_range": "", "ecosystem": "docker"}], "usedTechs": []}
    inv_82 = {"records": [{"repo": "c/b", "tech_key": "runtime:php", "kind": "runtime", "version_hint": "8.2", "declared_range": "", "ecosystem": "docker"}], "usedTechs": []}
    assert len(candidates.build_candidates(inv_80, root, repo_ids={"c/a": 1})) == 1     # 8.0 -> matches cycle 8.0
    assert candidates.build_candidates(inv_82, root, repo_ids={"c/b": 2}) == []          # 8.2 -> not cycle 8.0

def test_lifecycle_cycle_match_is_boundary_aware_not_substring(tmp_path):
    """Real production data: endoflife feed emits changeType='deprecation' (never 'eol').
    A node cycle '8' entry must NOT cross-match a repo pinned to node '18' (raw substring
    'cycle 8' in '18' would falsely match), but MUST match a repo on '8.19.0'."""
    root = str(tmp_path)
    kb_store.append_entries(root, "runtime:node", [ChangeEntry(
        techKey="runtime:node", date="2019-12-01", changeType="deprecation", title="Node 8 EOL",
        summary="", sourceUrl="https://x", sourceTier=1, affectedArea="cycle 8")])
    inv_18 = {"records": [{"repo": "c/c", "tech_key": "runtime:node", "kind": "runtime", "version_hint": "18", "declared_range": "", "ecosystem": "docker"}], "usedTechs": []}
    inv_819 = {"records": [{"repo": "c/d", "tech_key": "runtime:node", "kind": "runtime", "version_hint": "8.19.0", "declared_range": "", "ecosystem": "docker"}], "usedTechs": []}
    assert candidates.build_candidates(inv_18, root, repo_ids={"c/c": 3}) == []           # 18 -> not cycle 8
    assert len(candidates.build_candidates(inv_819, root, repo_ids={"c/d": 4})) == 1      # 8.19.0 -> matches cycle 8
