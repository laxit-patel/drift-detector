"""Build a SARIF 2.1.0 log from audit findings, so they can be uploaded to GitHub's Security tab.

CVE findings anchor to the repo's declaring manifest (from the inventory's sdk `file`); EOL
findings anchor to the repo directory. https://sarifweb.azurewebsites.net/
"""
from __future__ import annotations

_RULES = {
    "cve": {"id": "cve", "name": "vulnerable-dependency",
            "shortDescription": {"text": "Dependency with a known vulnerability (OSV)"}},
    "eol": {"id": "eol", "name": "end-of-life-runtime",
            "shortDescription": {"text": "End-of-life runtime or framework (endoflife.date)"}},
    "sunset": {"id": "sunset", "name": "retiring-vendor-api",
               "shortDescription": {"text": "Third-party API version scheduled for retirement"}},
}


def _locations_from_files(repo, files):
    locs = []
    for fl in files:
        uri, _, line = str(fl).rpartition(":")
        uri = uri or fl
        phys = {"artifactLocation": {"uri": f"{repo}/{uri}"}}
        if line.isdigit():
            phys["region"] = {"startLine": int(line)}
        locs.append({"physicalLocation": phys})
    return locs


def build_sarif(doc: dict, findings: list) -> dict:
    file_of = {}
    for r in doc.get("repos", []):
        for s in r.get("sdks", []):
            file_of[(r.get("path"), s.get("eco"), s.get("pkg"))] = s.get("file")

    rules: dict = {}
    results = []
    for f in findings:
        rid = f["kind"] if f["kind"] in _RULES else "cve"
        rules.setdefault(rid, _RULES[rid])
        if f.get("files"):                            # sunset findings carry precise file:line
            locations = _locations_from_files(f["repo"], f["files"])
        else:
            rel = None
            if f["kind"] == "cve":
                eco, _, pkg = f["ref"].partition("/")
                rel = file_of.get((f["repo"], eco, pkg))
            phys = {"artifactLocation": {"uri": f"{f['repo']}/{rel}" if rel else f"{f['repo']}"}}
            if rel:
                phys["region"] = {"startLine": 1}
            locations = [{"physicalLocation": phys}]
        results.append({
            "ruleId": rid,
            "level": "error" if f["status"] == "DEPRECATED" else "warning",
            "message": {"text": f"{f['ref']} {f['version']}: {f['detail']}"
                                + (f" (fix: {f['recommendation']})" if f.get("recommendation") else "")},
            "locations": locations,
            "properties": {"status": f["status"], "severity": f.get("severity"),
                           "source": f.get("source_url")},
        })

    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": "drift-detector",
                                "informationUri": "https://github.com/laxit-patel/drift-detector",
                                "rules": list(rules.values())}},
            "results": results,
        }],
    }
