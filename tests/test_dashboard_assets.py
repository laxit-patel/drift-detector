# tests/test_dashboard_assets.py
from pathlib import Path
VENDOR = Path(__file__).resolve().parent.parent / "agent" / "assets" / "vendor"

def test_vue_runtime_is_vendored_and_pinned():
    js = (VENDOR / "vue.global.prod.js").read_text(encoding="utf-8")
    assert len(js) > 50_000                       # the real runtime, not a stub
    assert "Vue" in js                            # exposes the global
    prov = (VENDOR / "PROVENANCE.md").read_text(encoding="utf-8")
    assert "vue" in prov.lower() and "http" in prov.lower()   # version + source URL recorded
    import re
    assert re.search(r"\b3\.\d+\.\d+\b", prov)    # a pinned 3.x version string
