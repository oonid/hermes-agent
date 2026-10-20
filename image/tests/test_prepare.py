import subprocess
import tempfile
import unittest
from pathlib import Path

PREPARE = Path(__file__).resolve().parents[1] / "prepare.sh"
IDENTITY = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]


def git(cwd, *args):
    return subprocess.run(["git", *IDENTITY, *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


class PrepareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.upstream = root / "upstream"
        self.patches = root / "patches"
        self.out = root / "out"
        self.upstream.mkdir()
        self.patches.mkdir()
        git(self.upstream, "init", "-q", "-b", "main")
        (self.upstream / "a.txt").write_text("one\n")
        git(self.upstream, "add", "a.txt")
        git(self.upstream, "commit", "-q", "-m", "base")
        git(self.upstream, "tag", "v1.0.0")
        self.tag_commit = git(self.upstream, "rev-parse", "HEAD")

    def tearDown(self):
        self.tmp.cleanup()

    def make_patch(self, name, content, subject):
        git(self.upstream, "checkout", "-q", "-b", f"work-{name}", "v1.0.0")
        (self.upstream / "a.txt").write_text(content)
        git(self.upstream, "commit", "-q", "-am", subject)
        patch = git(self.upstream, "format-patch", "-1", "--stdout")
        (self.patches / name).write_text(patch + "\n")
        git(self.upstream, "checkout", "-q", "main")

    def run_prepare(self):
        return subprocess.run(["bash", str(PREPARE), f"file://{self.upstream}", "v1.0.0",
                               str(self.patches), str(self.out)], capture_output=True, text=True)

    def test_empty_series_checks_out_the_tag_on_image_build(self):
        result = self.run_prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip().splitlines()[-1], self.tag_commit)
        self.assertEqual(git(self.out, "branch", "--show-current"), "image-build")

    def test_patches_are_applied_in_order(self):
        self.make_patch("0001-two.patch", "two\n", "make it two")
        (self.patches / "README.md").write_text("not a patch")
        result = self.run_prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.out / "a.txt").read_text(), "two\n")
        self.assertEqual(git(self.out, "log", "-1", "--format=%s"), "make it two")
        self.assertEqual(result.stdout.strip().splitlines()[-1], git(self.out, "rev-parse", "HEAD"))

    def test_a_patch_that_does_not_apply_fails(self):
        self.make_patch("0001-two.patch", "two\n", "make it two")
        self.make_patch("0002-three.patch", "three\n", "make it three")
        result = self.run_prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not apply", result.stderr)


if __name__ == "__main__":
    unittest.main()
