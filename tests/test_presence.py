# tests/test_presence.py
from agent.lib.presence import detect_presence, load_patterns
from agent.lib.gitlab_read import GitLabError

PATTERNS = [
    {"techKey": "api:amazon-sp-api", "query": "sellingpartnerapi", "label": "Amazon SP-API"},
    {"techKey": "api:walmart-marketplace", "query": "marketplace.walmartapis.com", "label": "Walmart"},
]

class FakeClient:
    def __init__(self, hits, raise_exc=None):
        self._hits = hits            # query -> list of blob dicts
        self._raise = raise_exc
    def search_blobs(self, project_id, query):
        if self._raise:
            raise self._raise
        return self._hits.get(query, [])

def test_detect_presence_emits_used_tech_on_hit():
    client = FakeClient({"sellingpartnerapi": [{"path": "src/Amazon.php", "data": "...sellingpartnerapi..."}]})
    used, note = detect_presence(client, 1, "clients/a", PATTERNS)
    assert note is None
    assert len(used) == 1
    assert used[0].tech_key == "api:amazon-sp-api"
    assert "src/Amazon.php" in used[0].evidence

def test_detect_presence_no_hits():
    used, note = detect_presence(FakeClient({}), 1, "clients/a", PATTERNS)
    assert used == [] and note is None

def test_detect_presence_search_unavailable_returns_note():
    used, note = detect_presence(FakeClient({}, raise_exc=GitLabError("404 search")), 1, "clients/a", PATTERNS)
    assert used == [] and note is not None      # coverage note, not silent

def test_load_patterns(tmp_path):
    p = tmp_path / "patterns.yaml"
    p.write_text("- {techKey: api:ebay, query: api.ebay.com, label: eBay}\n")
    pats = load_patterns(str(p))
    assert pats[0]["techKey"] == "api:ebay"
