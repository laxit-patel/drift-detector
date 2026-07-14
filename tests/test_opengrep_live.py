import os
import sys
import shutil
import pytest

from agent.lib.vendors import Vendor
from agent.lib.vendor_rules import write_ruleset
from agent.lib.opengrep import run_scan
from agent.lib.endpoints import build_endpoints


def _find_engine():
    for name in ("opengrep", "semgrep"):
        p = shutil.which(name) or os.path.join(os.path.dirname(sys.executable), name)
        if os.path.exists(p):
            return p
    return None


_ENGINE = _find_engine()


@pytest.mark.skipif(_ENGINE is None, reason="no opengrep/semgrep engine installed")
def test_live_endpoint_extraction_skips_comments(tmp_path):
    (tmp_path / "pay.php").write_text(
        '<?php\n'
        '// legacy: https://api.stripe.com/v9/dead\n'         # comment -> MUST be skipped
        '$u = "https://api.stripe.com/v1/charges";\n')
    (tmp_path / "app.js").write_text(
        'const u = "https://sellingpartnerapi-na.amazon.com/orders/v0/orders";\n')

    vendors = [Vendor("Stripe", "api:stripe", ("api.stripe.com",),
                      r'/(v\d+)'),
               Vendor("Amazon SP-API", "api:amazon-sp-api", ("sellingpartnerapi",),
                      r'/(v[0-9][0-9.]*|[0-9]{4}-[0-9]{2}-[0-9]{2})')]
    rules = tmp_path / "rules.yaml"
    write_ruleset(vendors, str(rules))

    res = run_scan(str(tmp_path), str(rules), engine=_ENGINE)
    eps = build_endpoints(res["matches"], str(tmp_path), vendors)

    by_key = {e["techKey"]: e for e in eps}
    assert by_key["api:stripe"]["version"] == "v1"          # the live code line, NOT the comment's v9
    assert all("v9" not in (e.get("version") or "") for e in eps)   # comment endpoint skipped
    assert by_key["api:amazon-sp-api"]["version"] == "v0"
