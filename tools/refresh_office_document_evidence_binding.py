from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "outputs/p4/office-document-workflow-evidence.json"
MANIFEST = ROOT / "catalog/p4/tool-manifests.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    for result in evidence["formats"].values():
        for artifact in (result["receipt"], result["framework_output"], result["artifact"]):
            path = ROOT / artifact["path"]
            if not path.is_file() or digest(path) != artifact["sha256"]:
                raise RuntimeError(f"stale office artifact: {artifact['path']}")
    implementation_hashes = evidence["implementation_hashes"]
    for relative in ("adapters/p4/office_document_workflow.py", "adapters/p4/officecli_adapter.py", "tools/wuji4.py"):
        if implementation_hashes.get(relative) != digest(ROOT / relative):
            raise RuntimeError(f"stale office implementation: {relative}")
    implementation_hashes["catalog/p4/tool-manifests.json"] = digest(MANIFEST)
    evidence["binding_refresh"] = {
        "reason": "video-render catalog binding revision changed; office execution artifacts and adapters are unchanged",
        "execution_repeated": False,
        "manifest_sha256": implementation_hashes["catalog/p4/tool-manifests.json"],
    }
    EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"evidence": EVIDENCE.relative_to(ROOT).as_posix(),
                      "manifest_sha256": implementation_hashes["catalog/p4/tool-manifests.json"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
