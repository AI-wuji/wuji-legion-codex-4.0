"""Check the public Python entry preserves native option-first invocation and failure."""
import io
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock
import wuji4


class MotionEntryTests(unittest.TestCase):
    def test_option_first_project_and_native_flags_are_forwarded_in_order(self):
        argv = ["--project", "a project", "render", "--fps", "24", "--workers", "2"]
        with mock.patch.object(sys, "argv", ["wuji4.py", "run-motion", *argv]), mock.patch.object(
                wuji4, "run_motion", return_value=0) as execute:
            with self.assertRaises(SystemExit) as caught:
                wuji4.main()
        self.assertEqual(0, caught.exception.code)
        execute.assert_called_once_with(argv)

    def test_native_failure_is_returned_without_a_success_wrapper(self):
        output = io.StringIO()
        with mock.patch.object(sys, "argv", ["wuji4.py", "run-motion", "check", "missing"]), mock.patch.object(
                wuji4, "run_motion", return_value=7), redirect_stdout(output):
            with self.assertRaises(SystemExit) as caught:
                wuji4.main()
        self.assertEqual(7, caught.exception.code)
        self.assertEqual("", output.getvalue())


if __name__ == "__main__":
    unittest.main()
