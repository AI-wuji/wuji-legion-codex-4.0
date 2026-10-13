import json
import re
import subprocess
import unittest

from test_core_cli import EXECUTABLE, ROOT


class CliHelpTests(unittest.TestCase):
    def help(self, *arguments):
        result = subprocess.run([str(EXECUTABLE), *arguments], cwd=ROOT, capture_output=True,
                                text=True, encoding="utf-8", timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_all_help_forms_have_the_same_complete_result(self):
        expected = self.help()
        for argument in ("help", "--help", "-h"):
            self.assertEqual(self.help(argument), expected)

    def test_each_implemented_command_is_documented(self):
        source = (ROOT / "src/main.rs").read_text(encoding="utf-8")
        implemented = set(re.findall(r'\("([a-z][a-z-]*)", \d+\)', source))
        documented = {command.split()[0] for command in self.help()["commands"]}
        self.assertTrue(implemented.issubset(documented), implemented - documented)

    def test_help_does_not_claim_acceptance_or_installation(self):
        result = self.help()
        self.assertEqual(result["stage"], "isolated-development")
        self.assertFalse(result["native_host_verified"])
        self.assertFalse(result["P7_installed"])
        self.assertEqual(result["gate_status"]["G6"], "not-claimed")


if __name__ == "__main__":
    unittest.main()
