"""Prepare the pinned Huashu Motion runtime inside this 5.0 project only."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

MOTION = (
    "huashu-motion", "0.3.1", "huashu-motion-0.3.1.tgz",
    "sha512-iFH6Nxy9YcKOfUW78jJKAplO5Xn0VOWK8X0ceMZAV6cQb5ScJEha3ixt5I7alKpCeiiPOvBj3wPnsm9Sv+2SLw==",
    "52467f99c602b76ba86d511d37acdfe93fa1e16e",
)
FFPROBE = (
    "@ffprobe-installer/win32-x64", "5.1.0", "ffprobe-installer-win32-x64-5.1.0.tgz",
    "sha512-jMGYeAgkrdn4e2vvYt/qakgHRE3CPju4bn5TmdPfoAm1BlX1mY9cyMd8gf5vSzI8gH8Zq5WQAyAkmekX/8TSTg==",
)
ROOT = Path(__file__).resolve().parents[4]


def integrity(path: Path) -> str:
    return "sha512-" + base64.b64encode(hashlib.sha512(path.read_bytes()).digest()).decode()


def npm_pack(root: Path, node: Path, package: tuple, source: Path | None = None) -> Path:
    cache = root / ".dev/tools"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / package[2]
    if not archive.exists():
        npm_cli = node.parent / "node_modules/npm/bin/npm-cli.js"
        if not npm_cli.is_file():
            raise ValueError(f"npm CLI not found beside configured Node: {npm_cli}")
        if source is None:
            target = f"{package[0]}@{package[1]}"
        else:
            target = str(source)
        result = subprocess.run(
            [str(node), str(npm_cli), "pack", target, "--pack-destination", str(cache),
             "--ignore-scripts", "--json", "--fetch-retries=0", "--fetch-timeout=60000"],
            check=True, capture_output=True, text=True, timeout=240,
        )
        packed = json.loads(result.stdout)[0]
        if packed["filename"] != package[2] or packed["integrity"] != package[3]:
            raise ValueError(f"Registry/source differs from the pinned package: {packed.get('id')}")
    if integrity(archive) != package[3]:
        raise ValueError(f"Archive integrity mismatch: {archive}")
    return archive


def unpack_motion_source(bundle: Path, temp: Path) -> Path:
    with zipfile.ZipFile(bundle) as archive:
        members = archive.infolist()
        tops = {PurePosixPath(item.filename).parts[0] for item in members if item.filename}
        expected_top = f"huashu-motion-{MOTION[4]}"
        if tops != {expected_top}:
            raise ValueError("Source ZIP must be the pinned Huashu Motion commit archive")
        root = (temp / next(iter(tops))).resolve()
        root.mkdir(parents=True)
        for item in members:
            path = PurePosixPath(item.filename)
            mode = item.external_attr >> 16
            if path.is_absolute() or ".." in path.parts or mode & 0o170000 == 0o120000:
                raise ValueError("Unsafe entry in Huashu Motion source archive")
            destination = (temp / Path(*path.parts)).resolve()
            if not destination.is_relative_to(root):
                raise ValueError("Huashu Motion source entry escapes its root")
            if item.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as incoming, destination.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
    metadata = json.loads((root / "package.json").read_text(encoding="utf-8"))
    if metadata.get("name") != MOTION[0] or metadata.get("version") != MOTION[1]:
        raise ValueError("Downloaded source package identity/version mismatch")
    return root


def unpack(archive: Path, target: Path) -> None:
    if target.exists():
        return  # The 5.0 launcher verifies every installed byte against the pinned archive.
    target.mkdir(parents=True)
    with tarfile.open(archive, "r:gz") as bundle:
        for entry in bundle:
            parts = PurePosixPath(entry.name).parts
            if (not parts or parts[0] != "package" or ".." in parts or "\\" in entry.name
                    or not entry.isfile()):
                raise ValueError(f"Unsupported npm archive entry: {entry.name}")
            destination = (target / Path(*parts[1:])).resolve()
            if not destination.is_relative_to(target.resolve()):
                raise ValueError("npm archive entry escapes install directory")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with bundle.extractfile(entry) as incoming, destination.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)


def copy_binary(source: Path, destination: Path) -> None:
    source = source.resolve(strict=True)
    if destination.exists():
        if hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(destination.read_bytes()).digest():
            raise ValueError(f"Existing private binary differs; preserved: {destination}")
    else:
        shutil.copy2(source, destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--node", type=Path)
    parser.add_argument("--chrome", type=Path)
    parser.add_argument("--ffmpeg", type=Path)
    parser.add_argument("--motion-source-zip", type=Path,
                        help="Completed FluxDown ZIP for the pinned Huashu Motion commit")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if sys.platform != "win32":
        raise ValueError("This setup helper is for the currently verified Windows runtime")
    if not (root / "legion/skills/wuji-legion-5-0/scripts/motion-graphics.mjs").is_file():
        raise ValueError("--root must be the active Wuji Legion 5.0 project")

    manifest_path = root / ".dev/motion-graphics/runtime.json"
    existing = json.loads(manifest_path.read_text(encoding="utf-8-sig")) if manifest_path.is_file() else {}
    node = (args.node or (Path(existing["node"]) if existing.get("node") else Path(shutil.which("node") or ""))).resolve(strict=True)
    version = subprocess.run([str(node), "--version"], check=True, capture_output=True, text=True, timeout=10).stdout.strip()
    if not version.startswith("v") or int(version[1:].split(".", 1)[0]) < 22:
        raise ValueError("Configured Node must be >=22")

    chrome_options = [args.chrome] if args.chrome else [Path(p) for p in (
        existing.get("chrome", ""),
        "C:/Program Files/Google/Chrome/Application/chrome.exe",
        "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    ) if p]
    chrome = next((p.resolve() for p in chrome_options if p.is_file()), None)
    if chrome is None:
        raise ValueError("Specify installed Chrome/Edge with --chrome")

    motion_archive = root / ".dev/tools" / MOTION[2]
    if not motion_archive.exists():
        if args.motion_source_zip is None:
            raise ValueError(
                "Pinned Motion package is not cached; provide a completed FluxDown archive "
                "with --motion-source-zip"
            )
        with tempfile.TemporaryDirectory(prefix="wuji-motion-source-") as temp_dir:
            source = unpack_motion_source(args.motion_source_zip.resolve(strict=True), Path(temp_dir))
            npm_pack(root, node, MOTION, source)
    motion_archive = npm_pack(root, node, MOTION)
    motion_install = root / ".dev/tools/huashu-motion-0.3.1"
    unpack(motion_archive, motion_install)

    ffprobe_archive = npm_pack(root, node, FFPROBE)
    ffprobe_install = root / ".dev/tools/ffprobe-installer-win32-x64-5.1.0"
    unpack(ffprobe_archive, ffprobe_install)
    private_bin = root / ".dev/motion-graphics/bin"
    private_bin.mkdir(parents=True, exist_ok=True)
    ffmpeg_candidates = [args.ffmpeg] if args.ffmpeg else [
        private_bin / "ffmpeg.exe", Path(shutil.which("ffmpeg") or "")]
    ffmpeg = next((p.resolve() for p in ffmpeg_candidates if p.is_file()), None)
    if ffmpeg is None:
        raise ValueError("Provide an installed FFmpeg path with --ffmpeg")
    copy_binary(ffmpeg, private_bin / "ffmpeg.exe")
    copy_binary(ffprobe_install / "ffprobe.exe", private_bin / "ffprobe.exe")

    runtime = {
        "schema_version": 1,
        "node": node.as_posix(),
        "chrome": chrome.as_posix(),
        "ffmpeg": ".dev/motion-graphics/bin/ffmpeg.exe",
        "ffprobe": ".dev/motion-graphics/bin/ffprobe.exe",
        "source": {
            "name": MOTION[0], "version": MOTION[1], "integrity": MOTION[3],
            "install_dir": ".dev/tools/huashu-motion-0.3.1",
            "archive": ".dev/tools/" + MOTION[2],
            "repository": "https://github.com/alchaincyf/huashu-motion",
            "ref": "v0.3.1", "commit": MOTION[4],
        },
    }
    if manifest_path.exists() and json.loads(manifest_path.read_text(encoding="utf-8-sig")) != runtime:
        raise ValueError("Existing runtime configuration differs; preserved for review")
    if not manifest_path.exists():
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(runtime, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    launcher = root / "legion/skills/wuji-legion-5-0/scripts/motion-graphics.mjs"
    return subprocess.run([str(node), str(launcher), "--root", str(root), "doctor"], check=False).returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError, subprocess.SubprocessError) as error:
        print(json.dumps({"success": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
