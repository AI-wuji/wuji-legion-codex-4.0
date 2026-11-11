from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROSTER = ROOT / "catalog/p3/expert-roster-5.0.json"
SOURCE = ROOT / "catalog/p3/experts.json"
PROFILE_ROOT = ROOT / "legion/skills/wuji-legion-5-0/experts"
EXPECTED_EXPERTS = {
    "wuji-architect", "wuji-automation", "wuji-av-producer", "wuji-business",
    "wuji-code-reviewer", "wuji-comfyui", "wuji-contract-reviewer", "wuji-course",
    "wuji-data-analyst", "wuji-diagnostician", "wuji-document", "wuji-engineer",
    "wuji-explorer", "wuji-file-operator", "wuji-film-planner", "wuji-frontend-visual",
    "wuji-media-reviewer", "wuji-motion-graphics", "wuji-publisher", "wuji-researcher",
    "wuji-reverse", "wuji-skill-packager", "wuji-tester", "wuji-threat-modeler", "wuji-writer",
    "wuji-film-analysis-adaptation",
}


def validate() -> dict:
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    roles = roster.get("roles")
    if not isinstance(roles, list) or len(roles) != 26:
        raise ValueError("The consolidated 5.0 roster must contain exactly 26 experts")
    ids = [item.get("id") for item in roles if isinstance(item, dict)]
    names = {value.rsplit("/", 1)[-1] for value in ids if isinstance(value, str)}
    if len(ids) != 26 or len(set(ids)) != 26 or names != EXPECTED_EXPERTS:
        raise ValueError("Expert roster IDs do not match the 26 consolidated profiles")
    known = {role["id"] for role in source.get("roles", [])}
    mapped = set()
    for role in roles:
        if not isinstance(role.get("responsibility"), str) or not role["responsibility"].strip():
            raise ValueError(f"Missing responsibility for {role.get('id')}")
        display_name = role.get("display_name_zh")
        if (not isinstance(display_name, str) or not display_name.strip()
                or not any("\u4e00" <= char <= "\u9fff" for char in display_name)):
            raise ValueError(f"Missing Chinese functional display name for {role.get('id')}")
        skill_root = PROFILE_ROOT.parent.resolve()
        profile = (PROFILE_ROOT / role.get("profile", "")).resolve(strict=True)
        if not profile.is_relative_to(skill_root) or not profile.is_file():
            raise ValueError(f"Profile must resolve inside the 5.0 expert directory: {role.get('id')}")
        if display_name not in profile.read_text(encoding="utf-8").splitlines()[0]:
            raise ValueError(f"Profile heading must include display name {display_name!r}: {role.get('id')}")
        refs = role.get("source_responsibilities")
        if not isinstance(refs, list) or not refs:
            raise ValueError(f"No merged P3 source responsibilities for {role['id']}")
        unknown = set(refs) - known
        if unknown:
            raise ValueError(f"Unknown P3 source responsibilities: {sorted(unknown)}")
        mapped.update(refs)
    missing = known - mapped
    if missing:
        raise ValueError(f"Unmerged P3 design responsibilities remain: {sorted(missing)}")
    return {"state": "valid_consolidated_expert_roster", "expert_count": len(roles),
            "source_responsibility_count": len(known), "profile_count": len(roles),
            "all_source_responsibilities_mapped": True}


if __name__ == "__main__":
    print(json.dumps(validate(), ensure_ascii=False))
