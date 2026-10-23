"""Prepare only the project-local motion runtime; never install global tools."""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

PACKAGE = ("huashu-motion", "0.1.1", "huashu-motion-0.1.1.tgz",
           "sha512-RJAUfR4/kP4FwE/41xwMMTx/Ua5KAGDqg6gwUFcg2DLsLvWaZCDtzL6DYD4FuCoPgCfd+Ek/EMB/xZrwq7QjUg==")
PROBE = ("@ffprobe-installer/win32-x64", "5.1.0", "ffprobe-installer-win32-x64-5.1.0.tgz",
         "sha512-jMGYeAgkrdn4e2vvYt/qakgHRE3CPju4bn5TmdPfoAm1BlX1mY9cyMd8gf5vSzI8gH8Zq5WQAyAkmekX/8TSTg==")
ROOT = Path(__file__).resolve().parents[1]


def archive(root, package, node):
    cache = root / ".dev/tools"
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / package[2]
    if not target.exists():
        npm = node.parent / "node_modules/npm/bin/npm-cli.js"
        if not npm.is_file():
            raise ValueError("The configured Node needs npm to download the pinned runtime")
        result = subprocess.run([str(node), str(npm), "pack", f"{package[0]}@{package[1]}",
                                 "--pack-destination", str(cache), "--ignore-scripts", "--json",
                                 "--fetch-retries=0", "--fetch-timeout=30000"],
                                check=True, capture_output=True, text=True, timeout=180)
        packed = json.loads(result.stdout)[0]
        if packed["integrity"] != package[3] or packed["filename"] != package[2]:
            raise ValueError("Registry result differs from the pinned release")
    actual = "sha512-" + base64.b64encode(hashlib.sha512(target.read_bytes()).digest()).decode()
    if actual != package[3]:
        raise ValueError(f"Archive integrity mismatch: {target}")
    return target


def unpack(source, target):
    if target.exists():
        return  # The launcher verifies every installed byte against the pinned archive.
    target.mkdir(parents=True)
    with tarfile.open(source, "r:gz") as bundle:
        for entry in bundle:
            relative = Path(entry.name).relative_to("package")
            destination = (target / relative).resolve()
            if not entry.isfile() or not destination.is_relative_to(target.resolve()):
                raise ValueError("Non-file or escaping package entry refused")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with bundle.extractfile(entry) as incoming, destination.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)


def copy_binary(source, destination):
    source = source.resolve(strict=True)
    if destination.exists():
        if hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(destination.read_bytes()).digest():
            raise ValueError(f"Existing private binary differs; preserved: {destination}")
    else:
        shutil.copy2(source, destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--node", type=Path, default=shutil.which("node"))
    parser.add_argument("--chrome", type=Path)
    parser.add_argument("--ffmpeg", type=Path, default=Path("E:/COMFYUI_dapao1/python_dapao313/Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe"))
    parser.add_argument("--ffprobe", type=Path)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if not (root / "catalog/p3/experts.json").is_file() or args.node is None:
        raise ValueError("Use the actual 4.0 project root and an installed Node >=22")
    node = args.node.resolve(strict=True)
    candidates = [args.chrome] if args.chrome else [Path(p) for p in (
        "C:/Program Files/Google/Chrome/Application/chrome.exe",
        "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")]
    chrome = next((p.resolve() for p in candidates if p and p.is_file()), None)
    if chrome is None:
        raise ValueError("Specify the installed Chromium browser with --chrome")
    source = archive(root, PACKAGE, node)
    install = root / ".dev/tools/huashu-motion-0.1.1"
    unpack(source, install)
    private = root / ".dev/motion-graphics/bin"
    private.mkdir(parents=True, exist_ok=True)
    suffix = ".exe" if sys.platform == "win32" else ""
    copy_binary(args.ffmpeg, private / ("ffmpeg" + suffix))
    if args.ffprobe is not None:
        probe = args.ffprobe
    elif sys.platform == "win32":
        probe_source = archive(root, PROBE, node)
        probe_dir = root / ".dev/tools/ffprobe-installer-win32-x64-5.1.0"
        unpack(probe_source, probe_dir)
        probe = probe_dir / "ffprobe.exe"
    else:
        raise ValueError("Specify --ffprobe on this platform")
    copy_binary(probe, private / ("ffprobe" + suffix))
    runtime = {"schema_version": 1, "node": node.as_posix(), "chrome": chrome.as_posix(),
               "ffmpeg": f".dev/motion-graphics/bin/ffmpeg{suffix}",
               "ffprobe": f".dev/motion-graphics/bin/ffprobe{suffix}",
               "source": {"name": PACKAGE[0], "version": PACKAGE[1], "integrity": PACKAGE[3],
                          "install_dir": ".dev/tools/huashu-motion-0.1.1",
                          "archive": ".dev/tools/" + PACKAGE[2]}}
    manifest = root / ".dev/motion-graphics/runtime.json"
    if manifest.exists() and json.loads(manifest.read_text(encoding="utf-8-sig")) != runtime:
        raise ValueError("Existing runtime configuration differs; preserved for explicit review")
    if not manifest.exists():
        manifest.write_text(json.dumps(runtime, ensure_ascii=False, indent=2), encoding="utf-8")
    launcher = root / "legion/skills/wuji-legion-4-0/scripts/motion-graphics.mjs"
    raise SystemExit(subprocess.run([str(node), str(launcher), "--root", str(root), "doctor"], check=False).returncode)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"success": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)

