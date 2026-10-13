"""Read-only P0 source audit. Not the Legion runtime or an execution host."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs/wuji-legion-4.0-execution-plan-v1.6-2026-10-03.md"
BASELINE_MANIFEST = ROOT / "docs/execution-baseline.json"
SOURCES = {
    "COURSE": Path("C:/Users/Administrator/.codex/attachments/c36774fd-9993-42b0-8eb7-b90c2aea2afc/已粘贴的文本.txt"),
    "WB-SOURCE": Path("C:/Users/Administrator/.workbuddy/plugins/marketplaces/my-experts/plugins/prompt-meta-team"),
    "RESEARCH": Path("C:/Users/Administrator/WorkBuddy/2026-09-30-11-17-38/research"),
    "FOREIGN": Path("E:/下载/新建文件夹/外来skill"),
    "YUELAN": Path("E:/下载/ai视频/悦蓝教案"),
    "E-SKILLS": Path("E:/BaiduNetdiskDownload/skill共享"),
}
MAX_HASH_BYTES = 32 * 1024 * 1024
TEXT_SUFFIXES = {".md", ".txt", ".json", ".jsonl", ".toml", ".yaml", ".yml", ".srt",
                 ".py", ".ps1", ".cjs", ".mjs", ".js", ".ts", ".sh", ".cs", ".go",
                 ".rs", ".html", ".css", ".xml", ".xsd"}
TEXT_NAMES = {"LICENSE", "LICENCE", "NOTICE", "COPYING", "README"}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def source_id(group: str, relative: str) -> str:
    return f"{group}:{hashlib.sha256(relative.encode('utf-8')).hexdigest()[:20]}"


def write_json(path: Path, value: object) -> None:
    # Generated reports only, confined to this new project's output directory.
    output_root = (ROOT / "outputs/p0").resolve()
    path = path.resolve()
    if not output_root.is_relative_to(ROOT.resolve()) or not path.is_relative_to(output_root):
        raise ValueError("report target is outside outputs/p0")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    temp = path.with_name(path.name + ".tmp")
    with temp.open("x", encoding="utf-8", newline="\n") as out:
        out.write(encoded)
    os.replace(temp, path)


def is_link(path: Path) -> bool:
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def scan_source(group: str, root: Path, hash_limit: int) -> list[dict]:
    if not root.exists():
        return [{"id": group, "path": str(root), "status": "missing"}]
    if is_link(root):
        return [{"id": group, "path": str(root), "status": "blocked_link"}]
    paths = [root] if root.is_file() else []
    errors = []
    if root.is_dir():
        for base, directories, names in os.walk(root, followlinks=False,
                                                onerror=lambda e: errors.append(str(e))):
            for name in list(directories):
                if is_link(Path(base) / name):
                    paths.append(Path(base) / name)
                    directories.remove(name)
            paths.extend(Path(base) / name for name in names)
    result = []
    for path in sorted(paths):
        relative = path.name if root.is_file() else path.relative_to(root).as_posix()
        row = {"id": source_id(group, relative), "group": group,
               "path": str(path), "relative": relative, "read_status": "discovered"}
        try:
            if is_link(path):
                row.update(status="blocked_link", hash_status="not_followed")
            else:
                before = path.stat()
                row.update(status="discovered", bytes=before.st_size,
                           mtime_ns=before.st_mtime_ns, suffix=path.suffix.lower(),
                           temporary_lock=path.name.startswith("~$"))
                if before.st_size <= hash_limit:
                    row.update(sha256=digest(path), hash_status="computed")
                    after = path.stat()
                    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                        row.pop("sha256", None)
                        row.update(status="changed_during_scan", hash_status="unstable")
                else:
                    row["hash_status"] = "deferred_size_budget"
        except OSError as error:
            row.update(status="unreadable", error=str(error), hash_status="failed")
        result.append(row)
    result.extend({"id": f"{group}:scan-error:{n}", "group": group,
                   "status": "scan_failed", "error": error} for n, error in enumerate(errors))
    return result


def compare_entries(left: list[dict], right: list[dict]) -> dict:
    def entries(rows):
        return {r["relative"]: r for r in rows if r.get("relative", "").endswith("/SKILL.md")}
    a, b = entries(left), entries(right)
    paired = []
    for name in sorted(a.keys() & b.keys()):
        ah, bh = a[name].get("sha256"), b[name].get("sha256")
        paired.append({"relative": name, "status": "unknown" if not ah or not bh
                       else "entry_equal" if ah == bh else "entry_changed",
                       "left_sha256": ah, "right_sha256": bh})
    ac = Counter(r.get("sha256") for r in a.values())
    bc = Counter(r.get("sha256") for r in b.values())
    # The supplied FOREIGN directory has an explicit skill共享 wrapper. Preserve
    # original paths and document the mapping instead of inferring identity by name.
    mapping = []
    for name, row in sorted(a.items()):
        normalized = name.removeprefix("skill共享/")
        target = b.get(normalized)
        if target is not None:
            ah, bh = row.get("sha256"), target.get("sha256")
            mapping.append({"left": name, "right": normalized,
                            "entry_match": None if not ah or not bh else ah == bh})
    def package_files(rows, prefix):
        return {r["relative"].removeprefix(prefix): r for r in rows if "relative" in r}
    af, bf = package_files(left, "skill共享/"), package_files(right, "")
    changed, unverified = [], []
    for name in sorted(af.keys() & bf.keys()):
        ah, bh = af[name].get("sha256"), bf[name].get("sha256")
        if not ah or not bh:
            unverified.append(name)
        elif ah != bh:
            changed.append(name)
    only_a, only_b = sorted(af.keys() - bf.keys()), sorted(bf.keys() - af.keys())
    full_equal = bool(af) and bool(bf) and not (only_a or only_b or changed or unverified)
    return {"left_count": len(a), "right_count": len(b), "paired": paired,
            "left_only": sorted(a.keys() - b.keys()), "right_only": sorted(b.keys() - a.keys()),
            "entry_hash_multiset_equal": None if None in ac or None in bc else ac == bc,
            "documented_mapping": "FOREIGN skill共享/ -> E-SKILLS root; original paths preserved",
            "mapped_entries": mapping, "package_left_only": only_a, "package_right_only": only_b,
            "package_changed": changed, "package_unverified": unverified,
            "full_package_equivalence": "equal_at_observation" if full_equal else "not_equal_or_unverified",
            "boundary": "Entry equality is not script/asset/license/package equality."}


def inspect_zip(path: Path, source: Path) -> dict:
    report = {"path": str(path), "status": "missing", "members": [],
              "executed_or_extracted": False, "source_equivalence": "unknown"}
    if not path.is_file():
        return report
    report.update(status="inspected", sha256=digest(path))
    with zipfile.ZipFile(path) as archive:
        items = archive.infolist()
        if len(items) > 10000:
            report.update(status="blocked", reason="member_count_budget")
            return report
        seen = set()
        total = 0
        wrapper = source.name + "/"
        report["documented_mapping"] = f"archive {wrapper} -> source root (must cover every member)"
        wrapper_valid = bool(items) and all(i.filename.replace("\\", "/").startswith(wrapper) for i in items)
        for item in items:
            name = item.filename.replace("\\", "/")
            parts = PurePosixPath(name).parts
            mode = item.external_attr >> 16
            unsafe = (name.startswith("/") or ".." in parts or ":" in name
                      or stat.S_ISLNK(mode) or name.casefold() in seen)
            seen.add(name.casefold())
            total += item.file_size
            ratio = item.file_size / max(1, item.compress_size)
            row = {"name": name, "bytes": item.file_size,
                   "compressed_bytes": item.compress_size, "unsafe_path_or_type": unsafe,
                   "compression_ratio": round(ratio, 2)}
            if unsafe or item.flag_bits & 1 or ratio > 200 or total > 256 * 1024 * 1024:
                report.update(status="blocked", reason="unsafe_or_unbounded_archive")
                report["members"].append(row)
                continue
            if item.is_dir():
                report["members"].append(row)
                continue
            if item.file_size <= MAX_HASH_BYTES:
                h = hashlib.sha256()
                with archive.open(item) as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        h.update(chunk)
                row["sha256"] = h.hexdigest()
            relative_parts = PurePosixPath(name[len(wrapper):]).parts if wrapper_valid else parts
            target = source.joinpath(*relative_parts)
            resolved = target.resolve()
            if resolved.is_relative_to(source.resolve()) and target.is_file() and not is_link(target):
                current = digest(target) if target.stat().st_size <= MAX_HASH_BYTES else None
                row["source_match"] = None if current is None or "sha256" not in row else current == row["sha256"]
            else:
                row["source_match"] = None
            report["members"].append(row)
    actual = [r for r in report["members"] if not r["name"].endswith("/")]
    if report["status"] != "blocked" and actual and all(r.get("source_match") is True for r in actual):
        report["source_equivalence"] = "all_archive_members_match_source;source_extras_not_compared"
    return report


def appendix_rows(text: str, letter: str, next_letter: str, count: int) -> list[dict]:
    section = re.search(rf"(?ms)^## 附录 {letter}\..*?(?=^## 附录 {next_letter}\.)", text)
    if section is None:
        raise ValueError(f"missing appendix {letter}")
    result = []
    pattern = r"^\| [a-z][a-z0-9-]+ \|" if letter == "A" else r"^\| \d+ \|"
    for line in section[0].splitlines():
        if re.match(pattern, line):
            cells = [v.strip() for v in line.strip("|").split("|")]
            result.append({"baseline_fields": cells, "review": "pending", "adopted": False})
    if len(result) != count:
        raise ValueError(f"appendix {letter} baseline changed")
    return result


def plan_rows(text: str, prefix: str, expected: int) -> list[dict]:
    rows = []
    for line in text.splitlines():
        if re.match(rf"^\| {prefix}\d{{2}}(?: |\b)", line):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            identifier = re.match(rf"{prefix}\d{{2}}", cells[0]).group()
            rows.append({"id": identifier, "baseline_fields": cells,
                         "implementation": "pending", "verification": "not_run"})
    ids = [r["id"] for r in rows]
    if set(ids) != {f"{prefix}{n:02}" for n in range(1, expected + 1)} or len(ids) != expected:
        raise ValueError(f"plan {prefix} baseline count/identity changed")
    return rows


def active_baseline() -> dict:
    from execution_baseline import load_active
    manifest = load_active(ROOT)
    return {key: manifest[key] for key in ("plan", "sha256", "version")}


def collect(hash_limit: int) -> dict:
    text = PLAN.read_text(encoding="utf-8-sig")
    if "执行基线 v1.6" not in text:
        raise ValueError("expected approved baseline v1.6")
    baseline = active_baseline()
    all_rows, summaries = [], {}
    by_group = {}
    for group, root in SOURCES.items():
        rows = scan_source(group, root, hash_limit)
        by_group[group] = rows
        all_rows.extend(rows)
        summaries[group] = {"path": str(root), "entries": len(rows),
                            "file_count": sum("bytes" in r for r in rows),
                            "bytes": sum(r.get("bytes", 0) for r in rows),
                            "hash_status_counts": dict(Counter(r.get("hash_status", "missing") for r in rows)),
                            "read_status": "discovered_only"}
        print(f"{group}: {summaries[group]['file_count']} files (not read)", flush=True)
    zip_audit = inspect_zip(SOURCES["WB-SOURCE"] / "dist/prompt-meta-team.zip", SOURCES["WB-SOURCE"])
    mirror = compare_entries(by_group["FOREIGN"], by_group["E-SKILLS"])
    requirements = plan_rows(text, "R", 72)
    tests = plan_rows(text, "T", 95)
    chat = plan_rows(text, "CHAT", 48)
    atoms = []
    for match in re.finditer(r"(?m)^\| ([A-P]0[1-8]) \| (.*)$", text):
        atoms.append({"id": match[1], "baseline_fields": [v.strip() for v in match[2].strip("|").split("|")],
                      "admission": "candidate", "source_evidence": "pending", "runtime": "not_implemented"})
    if len(atoms) != 128 or len({a["id"] for a in atoms}) != 128:
        raise ValueError("atom baseline changed")
    requirements_origin = {"version": "1.6", "plan": str(PLAN), "sha256": digest(PLAN)}
    summary = {"schema_version": 1, "observed_at": stamp(), "baseline": baseline, "requirements_origin": requirements_origin,
               "stage": "P0", "G0": "not_passed", "groups": summaries,
               "requirements": len(requirements), "acceptance_scenarios": len(tests),
               "conversation_topics": len(chat), "atom_candidates": len(atoms),
               "zip_status": zip_audit["status"], "mirror_entries": mirror,
               "boundary": "Filesystem inventory/hash/ZIP inspection is not reading, adoption, activation or completion."}
    out = ROOT / "outputs/p0"
    previous_sources = appendix_rows(text, "C", "D", 104)
    freshness = {"baseline": baseline, "observed_at": summary["observed_at"],
                 "stage": "P0", "G0": "not_passed", "sources": [
                     {"baseline_id": r["baseline_fields"][0], "name": r["baseline_fields"][1],
                      "official_entrypoint": None, "adopted": False, "latest_version": None,
                      "freshness": "pending_primary_source_review", "license": "pending",
                      "treatment": "undecided", "required_assets": "pending", "verification": "not_run"}
                     for r in previous_sources],
                 "boundary": "Source names/prior project status are not current capability or latest-version evidence."}
    required = [r for r in all_rows if r.get("group") == "COURSE"
                or (r.get("group") == "WB-SOURCE" and r.get("suffix") in {".md", ".jsonl", ".json"})
                or (r.get("group") == "RESEARCH" and r.get("relative") == "_kdocs_w5w6.md")
                or (r.get("group") == "FOREIGN" and (r.get("relative", "").endswith("/SKILL.md")
                    or (r.get("relative", "").startswith("skills基础版/") and r.get("suffix") in TEXT_SUFFIXES)))]
    coverage = {"observed_at": summary["observed_at"], "G0": "not_passed",
                "scope": "initial required textual entrypoints; necessary references/assets and Yuelan scope still pending",
                "reading_records": [], "required_entrypoints": required,
                "counts": {"discovered_entrypoints": len(required), "read_complete": 0},
                "boundary": "Scanning/extracting/printing alone does not mark reading complete."}
    for name, value in {"inventory.json": {"observed_at": summary["observed_at"], "files": all_rows},
                        "source-summary.json": summary, "zip-audit.json": zip_audit,
                        "requirement-map.json": {"baseline": baseline, "requirements_origin": requirements_origin, "requirements": requirements, "tests": tests},
                        "conversation-requirement-map.json": {"baseline": baseline, "requirements_origin": requirements_origin, "topics": chat},
                        "atom-candidates.json": {"baseline": baseline, "requirements_origin": requirements_origin, "candidates": atoms},
                        "source-coverage.json": coverage,
                        "responsibility-map.json": {"baseline": baseline, "requirements_origin": requirements_origin, "responsibilities": appendix_rows(text, "A", "B", 57)},
                        "source-baseline.json": {"baseline": baseline, "requirements_origin": requirements_origin, "sources": previous_sources},
                        "upstream-version-review.json": freshness}.items():
        # Refresh inventory without losing acknowledged evidence. Changed content
        # keeps an audit trail but cannot keep read-complete for a new hash.
        if name == "source-coverage.json" and (out / name).exists():
            prior = json.loads((out / name).read_text(encoding="utf-8"))
            value = refresh_coverage(value, prior, all_rows)
        if name == "upstream-version-review.json" and (out / name).exists():
            continue
        write_json(out / name, value)
    return summary


def refresh_coverage(current: dict, prior: dict, inventory_rows: list[dict] | None = None) -> dict:
    # Explicitly registered references survive inventory refresh, but must use
    # the freshly scanned hash rather than carrying forward old assertions.
    known = {r["id"]: r for r in inventory_rows or []}
    present = {r["id"] for r in current["required_entrypoints"]}
    for row in prior.get("required_entrypoints", []):
        if row.get("required_reason") and row["id"] not in present and row["id"] in known:
            fresh = dict(known[row["id"]])
            fresh["required_reason"] = row["required_reason"]
            current["required_entrypoints"].append(fresh)
    current["reading_records"] = prior.get("reading_records", [])
    older = {r["id"]: r for r in prior.get("required_entrypoints", [])}
    for row in current["required_entrypoints"]:
        previous = older.get(row["id"])
        if previous is None:
            continue
        if previous.get("required_reason"):
            row["required_reason"] = previous["required_reason"]
        if row.get("sha256") and row["sha256"] == previous.get("sha256"):
            for field in ("read_status", "acknowledged_ranges", "total_lines", "contiguous_read_through"):
                if field in previous:
                    row[field] = previous[field]
        elif previous.get("acknowledged_ranges"):
            row.update(read_status="needs_revalidation", prior_read_sha256=previous.get("sha256"))
    current_ids = {r["id"] for r in current["required_entrypoints"]}
    current["counts"]["discovered_entrypoints"] = len(current_ids)
    current["previously_required_missing"] = [r["id"] for r in prior.get("required_entrypoints", [])
                                               if r["id"] not in current_ids]
    for status in ("read-complete", "read-partial", "needs_revalidation"):
        current["counts"][status.replace("-", "_")] = sum(r.get("read_status") == status
                                                            for r in current["required_entrypoints"])
    return current


def require_source(path: Path, reason: str) -> dict:
    """Register a necessary textual reference without claiming it was read."""
    validate_text_source(path)
    if not reason.strip():
        raise ValueError("a required reference needs a specific reason")
    path = path.resolve()
    target = ROOT / "outputs/p0/source-coverage.json"
    value = json.loads(target.read_text(encoding="utf-8"))
    row = next((r for r in value["required_entrypoints"] if Path(r["path"]).resolve() == path), None)
    if row is None:
        inventory = json.loads((ROOT / "outputs/p0/inventory.json").read_text(encoding="utf-8"))
        source = next((r for r in inventory["files"] if r.get("path") and Path(r["path"]).resolve() == path), None)
        if source is None or source.get("sha256") != digest(path):
            raise ValueError("reference is missing from current inventory or has changed")
        row = dict(source)
        value["required_entrypoints"].append(row)
    row["required_reason"] = reason.strip()
    value["counts"]["discovered_entrypoints"] = len(value["required_entrypoints"])
    write_json(target, value)
    return {"source_id": row["id"], "read_status": row["read_status"], "required_reason": row["required_reason"]}


def validate_text_source(path: Path) -> None:
    allowed = any(path.resolve() == root.resolve() or (root.is_dir() and path.resolve().is_relative_to(root.resolve()))
                  for root in SOURCES.values()) or path.resolve() == PLAN.resolve()
    if not allowed or is_link(path) or (path.suffix.lower() not in TEXT_SUFFIXES and path.name.upper() not in TEXT_NAMES):
        raise ValueError("not an allowed ordinary text source")
    for ancestor in path.absolute().parents:
        if is_link(ancestor):
            raise ValueError("source has a link/reparse ancestor")
    if not path.is_file() or path.stat().st_size > MAX_HASH_BYTES:
        raise ValueError("source is missing or exceeds the text audit budget")


def read_text_slice(path: Path, start: int, max_bytes: int) -> None:
    # Caller explicitly reads bounded output; this command does NOT claim read-complete.
    if start < 1 or max_bytes < 256 or max_bytes > 10000:
        raise ValueError("invalid bounded read")
    validate_text_source(path)
    raw = path.read_bytes()
    lines = raw.decode("utf-8-sig").splitlines()
    if start > len(lines):
        raise ValueError("start exceeds actual text")
    selected, used = [], 0
    for number, line in enumerate(lines[start - 1:], start):
        item = f"{number}: {line}"
        size = len((item + "\n").encode("utf-8"))
        if used + size > max_bytes:
            break
        selected.append(item)
        used += size
    if not selected:
        raise ValueError("single line exceeds read budget; use a documented alternate reader")
    end = start + len(selected) - 1
    print(json.dumps({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                      "start": start, "end": end, "total_lines": len(lines),
                      "next_start": end + 1 if end < len(lines) else None}, ensure_ascii=False))
    print("\n".join(selected))


def record_reading(path: Path, expected_hash: str, start: int, end: int, note: str) -> dict:
    """Explicit reviewer acknowledgement; never inferred from output or extraction."""
    validate_text_source(path)
    path = path.resolve()
    target = ROOT / "outputs/p0/source-coverage.json"
    value = json.loads(target.read_text(encoding="utf-8"))
    row = next((r for r in value["required_entrypoints"] if Path(r["path"]).resolve() == path), None)
    if row is None:
        raise ValueError("source is not a registered required entrypoint")
    raw = path.read_bytes()
    actual_hash = hashlib.sha256(raw).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash) or actual_hash != expected_hash:
        raise ValueError("reading evidence hash is stale or invalid")
    lines = raw.decode("utf-8-sig").splitlines()
    if not 1 <= start <= end <= len(lines) or not note.strip():
        raise ValueError("invalid acknowledged reading range/note")
    if row.get("sha256") != actual_hash:
        raise ValueError("inventory hash no longer matches; review source change first")
    ranges = row.setdefault("acknowledged_ranges", [])
    if [start, end] not in ranges:
        ranges.append([start, end])
    coverage = 0
    for a, b in sorted(ranges):
        if a > coverage + 1:
            break
        coverage = max(coverage, b)
    row["read_status"] = "read-complete" if coverage == len(lines) else "read-partial"
    row["total_lines"] = len(lines)
    row["contiguous_read_through"] = coverage
    value["reading_records"].append({"source_id": row["id"], "sha256": actual_hash,
                                      "range": [start, end], "note": note,
                                      "recorded_at": stamp(), "kind": "explicit_reviewer_acknowledgement"})
    value["counts"]["read_complete"] = sum(r.get("read_status") == "read-complete"
                                           for r in value["required_entrypoints"])
    value["counts"]["read_partial"] = sum(r.get("read_status") == "read-partial"
                                          for r in value["required_entrypoints"])
    write_json(target, value)
    return {"source_id": row["id"], "read_status": row["read_status"],
            "contiguous_read_through": coverage, "total_lines": len(lines)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    collect_parser = sub.add_parser("collect")
    collect_parser.add_argument("--hash-limit-mib", type=int, default=32)
    read_parser = sub.add_parser("read")
    read_parser.add_argument("--path", type=Path, required=True)
    read_parser.add_argument("--start", type=int, default=1)
    read_parser.add_argument("--max-bytes", type=int, default=7500)
    record_parser = sub.add_parser("record-reading")
    record_parser.add_argument("--path", type=Path, required=True)
    record_parser.add_argument("--sha256", required=True)
    record_parser.add_argument("--start", type=int, required=True)
    record_parser.add_argument("--end", type=int, required=True)
    record_parser.add_argument("--note", required=True)
    require_parser = sub.add_parser("require")
    require_parser.add_argument("--path", type=Path, required=True)
    require_parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    if args.command == "collect":
        if not 1 <= args.hash_limit_mib <= 128:
            parser.error("hash budget must be 1..128 MiB per file")
        result = collect(args.hash_limit_mib * 1024 * 1024)
        print(f"P0 inventory created; G0={result['G0']}")
    elif args.command == "read":
        read_text_slice(args.path, args.start, args.max_bytes)
    elif args.command == "require":
        print(json.dumps(require_source(args.path, args.reason), ensure_ascii=False))
    else:
        print(json.dumps(record_reading(args.path, args.sha256, args.start, args.end, args.note),
                         ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        raise SystemExit(main())
    except (OSError, ValueError, zipfile.BadZipFile, UnicodeError) as error:
        print(f"P0 audit failed: {error}", file=sys.stderr)
        raise SystemExit(1)
