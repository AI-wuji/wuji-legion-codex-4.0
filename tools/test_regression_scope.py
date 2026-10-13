import unittest
from unittest import mock

import run_audit_tests as runner
import run_p6_regressions as regressions


class RegressionScopeTests(unittest.TestCase):
    def test_default_suite_loads_only_explicit_core_modules(self):
        with mock.patch.object(runner.unittest.defaultTestLoader, "discover") as discover, mock.patch.object(
                runner.unittest.defaultTestLoader, "loadTestsFromNames", return_value="core-suite") as load:
            self.assertEqual(runner.build_suite(), "core-suite")
        discover.assert_not_called()
        load.assert_called_once_with(runner.CORE_TEST_MODULES)
        self.assertEqual(len(runner.CORE_TEST_MODULES), len(set(runner.CORE_TEST_MODULES)))

    def test_software_modules_are_not_in_the_default_profile(self):
        software_modules = {
            "test_ffmpeg_workflow", "test_media_workflow", "test_media_probe_evidence",
            "test_office_document_workflow", "test_officecli_workflow", "test_officecli_adapter",
            "test_p4_tool_binding", "test_p4_adapters", "test_p6_office_evidence",
            "test_render_reading_batch",
        }
        self.assertTrue(software_modules.isdisjoint(runner.CORE_TEST_MODULES))

    def test_software_discovery_requires_an_explicit_request(self):
        with mock.patch.object(runner.unittest.defaultTestLoader, "discover", return_value="software-suite") as discover:
            self.assertEqual(runner.build_suite(include_software_tests=True), "software-suite")
        discover.assert_called_once_with(str(runner.ROOT / "tools"), pattern="test_*.py")

    def test_both_runners_share_the_same_suite_boundary(self):
        self.assertIs(regressions.build_suite, runner.build_suite)
        self.assertIs(regressions.arguments, runner.arguments)


if __name__ == "__main__":
    unittest.main(verbosity=2)
