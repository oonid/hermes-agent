import subprocess
import unittest
from pathlib import Path

SLIM = Path(__file__).resolve().parents[1] / "slim.sh"


def slim(*args):
    return subprocess.run(["bash", str(SLIM), *args], capture_output=True, text=True)


class SlimArgumentsTest(unittest.TestCase):
    def test_unknown_variant_is_refused(self):
        result = slim("bogus")
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage", result.stderr)

    def test_missing_variant_is_refused(self):
        self.assertEqual(slim().returncode, 2)

    def test_full_changes_nothing(self):
        result = slim("full")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
