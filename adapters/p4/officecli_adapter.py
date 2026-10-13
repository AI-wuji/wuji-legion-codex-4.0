from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

PINNED_VERSION = "1.0.152"
PINNED_SHA256 = "047705402974c3690a4437e55f620d03afac4beba4fdd28fdb59af610a3afff2"
DEFAULT_BINARY = Path("C:/Users/Administrator/AppData/Local/OfficeCli/officecli.exe")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protected_snapshot() -> dict:
    codex = Path("C:/Users/Administrator/.codex/config.toml")
    office = Path("C:/Users/Administrator/.officecli")
    configuration = office / "config.json"
    if configuration.is_file():
        values = json.loads(configuration.read_text(encoding="utf-8"))
        if any(key.casefold() == "log" and value is True for key, value in values.items()):
            raise PermissionError("Existing global OfficeCLI logging enabled; isolated execution must not write global logs")
    files = {str(codex): digest(codex) if codex.is_file() else None}
    if office.is_dir():
        for path in sorted(office.rglob("*")):
            if path.is_file():
                if path.stat().st_size > 4 * 1024 * 1024:
                    raise PermissionError("Global OfficeCLI state exceeds bounded protection snapshot")
                files[str(path)] = digest(path)
    return files


class OfficeCliAdapter:
    def __init__(self, workspace: Path, binary: Path = DEFAULT_BINARY):
        self.workspace = workspace.resolve(strict=True)
        development = Path(__file__).resolve().parents[2] / ".dev"
        if not self.workspace.is_relative_to(development.resolve(strict=True)) or self.workspace == development.resolve():
            raise PermissionError("OfficeCLI development adapter requires a separate project .dev workspace")
        if not binary.is_file() or binary.is_symlink() or digest(binary) != PINNED_SHA256:
            raise PermissionError("OfficeCLI exact original release binary hash is not available")
        self.binary = binary.resolve(strict=True)
        self.environment = dict(os.environ, OFFICECLI_NO_AUTO_INSTALL="1", OFFICECLI_SKIP_UPDATE="1",
                                OFFICECLI_NO_AUTO_RESIDENT="1")
        self.protected = protected_snapshot()
        self.owned = set()
        self.receipts = []
        result = self._invoke(["--version"])
        if result["stdout"].strip() != PINNED_VERSION:
            raise PermissionError("OfficeCLI observed version differs from pinned original release")

    def _invoke(self, arguments: list[str]) -> dict:
        if digest(self.binary) != PINNED_SHA256 or protected_snapshot() != self.protected:
            raise PermissionError("Pinned binary or protected configuration changed")
        completed = subprocess.run([str(self.binary), *arguments], cwd=self.workspace,
                                   env=self.environment, capture_output=True, timeout=30,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if len(completed.stdout) + len(completed.stderr) > 4 * 1024 * 1024:
            raise RuntimeError("OfficeCLI bounded response exceeded; never silently truncate")
        result = {"arguments": arguments, "exit_code": completed.returncode,
                  "stdout": completed.stdout.decode("utf-8", errors="replace"),
                  "stderr": completed.stderr.decode("utf-8", errors="replace"),
                  "owned_process_exit_observed": True, "auto_install": False,
                  "auto_update": False, "auto_resident": False}
        self.receipts.append(result)
        if protected_snapshot() != self.protected:
            raise PermissionError("Protected global configuration changed during OfficeCLI action")
        if completed.returncode != 0:
            raise RuntimeError("OfficeCLI action failed; retain original action receipt, do not blind retry")
        return result

    def file(self, relative: str) -> Path:
        if not relative or any(character in relative for character in "/\\:") or relative.endswith((".", " ")):
            raise PermissionError("Only a single new local Office file name is accepted")
        path = self.workspace / relative
        if path.is_symlink() or path.resolve().parent != self.workspace:
            raise PermissionError("OfficeCLI target escapes its isolated workspace")
        if path.suffix not in (".pptx", ".docx", ".xlsx"):
            raise PermissionError("Unsupported bounded Office format")
        return path

    def create(self, relative: str) -> dict:
        path = self.file(relative)
        if path.exists():
            raise FileExistsError("Never overwrite a preexisting Office file")
        result = self._invoke(["create", str(path), "--locale", "en-US"])
        if not path.is_file():
            raise RuntimeError("OfficeCLI create returned without the actual file")
        self.owned.add(relative)
        return result

    def action(self, operation: str, relative: str, *arguments: str) -> dict:
        path = self.file(relative)
        if relative not in self.owned or not path.is_file():
            raise PermissionError("OfficeCLI may act only on this instance's newly created files")
        if operation not in {"add", "set", "get", "view", "check", "close"}:
            raise PermissionError("OfficeCLI command outside bounded native action allowlist")
        if operation == "view" and arguments not in (("outline",), ("html",)):
            raise PermissionError("Only bounded outline/HTML views; no live watch or external screenshot engine")
        if any(argument in {"--force", "--open", "--serve", "--output", "-o"} for argument in arguments):
            raise PermissionError("No external paths, overwrite or resident flags")
        if len(arguments) > 32 or sum(len(argument.encode("utf-8")) for argument in arguments) > 8192:
            raise PermissionError("OfficeCLI bounded argument count/byte cap exceeded")
        if operation in {"add", "set", "get"}:
            if path.suffix != ".pptx" or not arguments or not re.fullmatch(r"/(?:slide\[[1-9][0-9]*\](?:/shape\[[1-9][0-9]*\])?)?", arguments[0]):
                raise PermissionError("Only exact bounded PPTX selectors are admitted")
            options = list(arguments[1:])
            allowed_properties = {"title", "background", "text", "x", "y", "width", "height", "font", "size", "color", "bold", "italic"}
            while options:
                flag = options.pop(0)
                if flag == "--json" and operation == "get":
                    continue
                if not options or flag not in {"--type", "--prop"} or operation == "get":
                    raise PermissionError("Undeclared OfficeCLI argument")
                value = options.pop(0)
                if flag == "--type":
                    if operation != "add" or value not in {"slide", "shape"}:
                        raise PermissionError("Unsupported bounded OfficeCLI element type")
                elif "=" not in value or value.split("=", 1)[0] not in allowed_properties:
                    raise PermissionError("External assets or undeclared OfficeCLI property")
        if operation in {"check", "close"} and arguments:
            raise PermissionError("Check/close accepts no extra target or option")
        return self._invoke([operation, str(path), *arguments])

    def observe(self, operation: str, relative: str, *arguments: str) -> dict:
        path = self.file(relative)
        if not path.is_file():
            raise FileNotFoundError(str(path))
        if operation not in {"validate", "view", "get"}:
            raise PermissionError("OfficeCLI observation is outside the bounded allowlist")
        if operation == "validate" and arguments:
            raise PermissionError("Validate accepts no extra option")
        if operation == "view" and arguments not in (("outline",), ("html",)):
            raise PermissionError("Only bounded outline/HTML views are admitted")
        if operation == "get":
            if len(arguments) != 1 or not re.fullmatch(r"/(?:body|[A-Za-z][A-Za-z0-9 _-]{0,30})(?:/[A-Za-z0-9_\[\]@=-]{1,40})?", arguments[0]):
                raise PermissionError("Only bounded document readback paths are admitted")
        return self._invoke([operation, str(path), *arguments])
