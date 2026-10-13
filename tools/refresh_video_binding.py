from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "catalog/p4/tool-manifests.json"
TARGET = "video-render"
IMPLEMENTATIONS = (
    "adapters/p4/ffmpeg_workflow.py",
    "adapters/p4/media_workflow.py",
    "tools/wuji4.py",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate manifest key")
        result[key] = value
    return result


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
    tools = manifest.get("tools")
    if manifest.get("schema_version") != 1 or not isinstance(tools, list):
        raise ValueError("unsupported tool manifest")
    targets = [tool for tool in tools if isinstance(tool, dict) and tool.get("id") == TARGET]
    if len(targets) != 1:
        raise ValueError("exactly one video-render tool is required")
    tool = targets[0]
    binding = tool.get("reviewed_binding")
    if not isinstance(binding, dict):
        raise ValueError("reviewed video binding is required")
    binding["revision"] = int(binding["revision"]) + 1
    binding["implementation_hashes"] = {relative: digest(ROOT / relative) for relative in IMPLEMENTATIONS}
    failures = tool.setdefault("action_contract", {}).setdefault("failure", [])
    if "binding-drift-before-dispatch" not in failures:
        failures.append("binding-drift-before-dispatch")
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"tool": TARGET, "revision": binding["revision"],
                      "manifest_sha256": digest(MANIFEST),
                      "implementation_hashes": binding["implementation_hashes"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
