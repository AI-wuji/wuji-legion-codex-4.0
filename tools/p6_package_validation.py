from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import stat
import zipfile

MAX_ARCHIVE_ENTRIES = 10000
MAX_TOTAL_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
EMBEDDED_MANIFEST_PATH = "p6/outputs/p6/release-manifest.json"
SIDECAR_PATH = "outputs/p6/release-manifest.json"
EXTERNAL_ARCHIVE_ATTESTATIONS = frozenset({"outputs/p6/full-audit-report.json"})
CHECK_KEYS = ("archive_exists", "archive_hash_matches", "embedded_manifest_valid",
              "declared_files_match", "archive_entries_closed", "path_safe")


def validate_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise ValueError("Relative POSIX file path required")
    if any(character in value for character in '\\:<>"|?*') or any(ord(character) < 32 for character in value):
        raise ValueError("Ambiguous Windows path")
    for component in value.split("/"):
        if component in ("", ".", "..") or component.endswith((".", " ")):
            raise ValueError("Noncanonical path")
        base = component.split(".")[0].casefold()
        if base in {"con", "prn", "aux", "nul", "conin$", "conout$"} or re.fullmatch(r"(?:com|lpt)[1-9¹²³]", base):
            raise ValueError("Windows device path")
    return value


def validate_package_file_path(value: object) -> str:
    relative = validate_relative_path(value)
    if relative.casefold() in EXTERNAL_ARCHIVE_ATTESTATIONS:
        raise ValueError("An audit of this archive must stay outside its own hashed file closure")
    parts = relative.casefold().split("/")
    if any(part in {".dev", "target", ".git", ".codex", ".agents", "node_modules", "__pycache__"} for part in parts) or parts[0] == "release":
        raise ValueError("Excluded runtime directory")
    name = parts[-1]
    if name.startswith((".env", "credentials", "secrets")) or name == "auth.json" or name.endswith((".db", ".sqlite", ".sqlite3", "-wal", "-shm", ".pem", ".key", ".pfx", ".pyc")):
        raise ValueError("Private or runtime file")
    return relative


def confined_path(root: Path, relative: object) -> Path:
    relative = validate_relative_path(relative)
    canonical_root = root.resolve(strict=True)
    candidate = canonical_root
    for component in relative.split("/"):
        candidate = candidate / component
        if candidate.is_symlink() or getattr(candidate, "is_junction", lambda: False)():
            raise ValueError("Linked package path")
        try:
            if getattr(candidate.lstat(), "st_file_attributes", 0) & 0x400:
                raise ValueError("Reparse package path")
        except FileNotFoundError:
            pass
    if not candidate.resolve().is_relative_to(canonical_root):
        raise ValueError("Package path escapes root")
    return candidate


def strict_json(value: bytes | str) -> dict:
    def unique(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("Duplicate manifest key")
            result[key] = item
        return result

    def reject(value):
        raise ValueError("Nonfinite number")

    parsed = json.loads(value, object_pairs_hook=unique, parse_constant=reject)
    if not isinstance(parsed, dict):
        raise ValueError("Manifest object required")
    return parsed


def stream_digest(stream, limit: int) -> tuple[int, str]:
    total = 0
    checksum = hashlib.sha256()
    while True:
        chunk = stream.read(min(1024 * 1024, limit - total + 1))
        if not chunk:
            return total, checksum.hexdigest()
        total += len(chunk)
        if total > limit:
            raise ValueError("Byte budget exceeded")
        checksum.update(chunk)


def manifest_file_entries(entries: object, archive_path: str) -> list[dict]:
    if not isinstance(entries, list) or not entries or len(entries) >= MAX_ARCHIVE_ENTRIES:
        raise ValueError("Invalid manifest file count")
    seen = set()
    total = 0
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "bytes", "sha256"}:
            raise ValueError("Invalid file declaration")
        relative = validate_package_file_path(entry["path"])
        if relative.casefold() in seen or relative.casefold() in {SIDECAR_PATH.casefold(), archive_path.casefold()}:
            raise ValueError("Duplicate or self-referencing file")
        seen.add(relative.casefold())
        if type(entry["bytes"]) is not int or entry["bytes"] < 0 or not isinstance(entry["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            raise ValueError("Invalid file size/hash")
        total += entry["bytes"]
        if total > MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise ValueError("Manifest byte budget exceeded")
    return entries


def package_consistency(root: Path, release_manifest: dict) -> dict[str, object]:
    result = dict.fromkeys(CHECK_KEYS, False)
    result["passed"] = False
    try:
        archive_declaration = release_manifest["archive"]
        archive_path = validate_package_file_path(archive_declaration["path"])
        if archive_declaration["verification"] != "external-sidecar":
            raise ValueError("External sidecar required")
        if release_manifest["embedded_manifest"] != {"path": EMBEDDED_MANIFEST_PATH, "archive_sha256": None, "archive_hash_scope": "external-sidecar"}:
            raise ValueError("Invalid embedded declaration")
        files = manifest_file_entries(release_manifest["files"], archive_path)
        package = confined_path(root, archive_path)
        result["archive_exists"] = package.is_file()
        if not result["archive_exists"] or package.stat().st_size > MAX_TOTAL_UNCOMPRESSED_BYTES:
            return result
        with package.open("rb") as package_stream:
            result["archive_hash_matches"] = stream_digest(package_stream, MAX_TOTAL_UNCOMPRESSED_BYTES)[1] == archive_declaration["sha256"]
            if not result["archive_hash_matches"]:
                return result
            package_stream.seek(0)
            with zipfile.ZipFile(package_stream) as archive:
                items = archive.infolist()
                names = [item.filename for item in items]
                if len(items) > MAX_ARCHIVE_ENTRIES or len(set(name.casefold() for name in names)) != len(names):
                    raise ValueError("Duplicate/unbounded ZIP entries")
                if sum(item.file_size for item in items) > MAX_TOTAL_UNCOMPRESSED_BYTES:
                    raise ValueError("Unbounded decompression")
                for item in items:
                    name = validate_relative_path(item.orig_filename)
                    if name != item.filename or not name.startswith("p6/"):
                        raise ValueError("Invalid ZIP root")
                    validate_package_file_path(name[3:])
                    mode = stat.S_IFMT(item.external_attr >> 16)
                    if item.is_dir() or mode not in (0, stat.S_IFREG) or item.flag_bits & 1 or item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                        raise ValueError("Unsafe ZIP member")
                result["path_safe"] = True
                result["archive_entries_closed"] = set(names) == {f"p6/{entry['path']}" for entry in files} | {EMBEDDED_MANIFEST_PATH}
                if not result["archive_entries_closed"]:
                    return result
                info = archive.getinfo(EMBEDDED_MANIFEST_PATH)
                if info.file_size > MAX_MANIFEST_BYTES:
                    raise ValueError("Manifest byte budget exceeded")
                embedded = strict_json(archive.read(info).decode("utf-8"))
                expected = dict(release_manifest)
                expected.pop("embedded_manifest")
                expected["archive"] = dict(archive_declaration, sha256=None)
                result["embedded_manifest_valid"] = (
                    json.dumps(embedded, sort_keys=True) == json.dumps(expected, sort_keys=True)
                )
                if not result["embedded_manifest_valid"]:
                    return result
                for entry in files:
                    source = confined_path(root, entry["path"])
                    info = archive.getinfo(f"p6/{entry['path']}")
                    if not source.is_file() or source.stat().st_size != entry["bytes"] or info.file_size != entry["bytes"]:
                        return result
                    with source.open("rb") as stream:
                        if stream_digest(stream, entry["bytes"])[1] != entry["sha256"]:
                            return result
                    with archive.open(info) as stream:
                        if stream_digest(stream, entry["bytes"])[1] != entry["sha256"]:
                            return result
                result["declared_files_match"] = True
        result["passed"] = all(result[key] for key in CHECK_KEYS)
    except Exception as error:
        result["error"] = type(error).__name__
        result["passed"] = False
    return result
