import importlib.util
from pathlib import Path
import tempfile
import unittest

from p6_acceptance import ROOT

SPEC = importlib.util.spec_from_file_location("wuji4_office_adapter_tests", ROOT / "adapters/p4/officecli_adapter.py")
OFFICE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OFFICE)


class OfficeCliAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="office-adapter-policy-", dir=ROOT / ".dev")
        self.workspace = Path(self.temporary.name).resolve()
        self.workspace.relative_to((ROOT / ".dev").resolve())
        self.addCleanup(self.temporary.cleanup)
        self.adapter = object.__new__(OFFICE.OfficeCliAdapter)
        self.adapter.workspace = self.workspace
        self.adapter.owned = {"owned.pptx"}
        (self.workspace / "owned.pptx").write_bytes(b"policy fixture, not an Office artifact")
        self.invocations = []
        self.adapter._invoke = lambda arguments: self.invocations.append(arguments) or {"exit_code": 0}

    def test_policy_only_allows_declared_text_pptx_arguments(self):
        self.adapter.action("set", "owned.pptx", "/slide[1]/shape[2]", "--prop", "text=Safe declared text")
        self.assertEqual(len(self.invocations), 1)

    def test_never_overwrites_preexisting_file(self):
        with self.assertRaises(FileExistsError):
            self.adapter.create("owned.pptx")
        self.assertEqual(self.invocations, [])

    def test_traversal_and_absolute_paths_fail_before_native_action(self):
        for relative in ("../outside.pptx", "C:/outside.pptx", "nested/file.pptx", "file.pptx "):
            with self.subTest(path=relative), self.assertRaises(PermissionError):
                self.adapter.file(relative)

    def test_unowned_files_and_global_commands_are_not_admitted(self):
        (self.workspace / "other.pptx").write_bytes(b"not owned")
        with self.assertRaises(PermissionError):
            self.adapter.action("get", "other.pptx", "/")
        for operation in ("install", "config", "open", "watch", "mcp"):
            with self.subTest(operation=operation), self.assertRaises(PermissionError):
                self.adapter.action(operation, "owned.pptx")

    def test_external_asset_properties_and_output_paths_fail_closed(self):
        for arguments in (("/slide[1]", "--type", "image", "--prop", "src=C:/private.png"),
                          ("/slide[1]/shape[1]", "--prop", "image=https://example.com/private"),
                          ("/slide[1]/shape[1]", "--output", "C:/outside")):
            with self.subTest(arguments=arguments), self.assertRaises(PermissionError):
                self.adapter.action("add", "owned.pptx", *arguments)

    def test_selector_escape_and_live_browser_view_are_denied(self):
        with self.assertRaises(PermissionError):
            self.adapter.action("get", "owned.pptx", "/slide[1]/../shape[1]")
        with self.assertRaises(PermissionError):
            self.adapter.action("view", "owned.pptx", "screenshot")


if __name__ == "__main__":
    unittest.main()
