import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import detect_release as d


def release(tag="v0.22.2", draft=False, prerelease=False):
    return lambda url: {"tag_name": tag, "draft": draft, "prerelease": prerelease}


class PatchHashTest(unittest.TestCase):
    def test_empty_series_has_a_fixed_hash(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            self.assertEqual(d.patch_hash(Path(a)), d.patch_hash(Path(b)))
            self.assertEqual(len(d.patch_hash(Path(a))), 8)

    def test_hash_follows_patch_content_and_ignores_other_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            empty = d.patch_hash(p)
            (p / "README.md").write_text("notes")
            self.assertEqual(d.patch_hash(p), empty)
            (p / "0001-fix.patch").write_text("one")
            one = d.patch_hash(p)
            self.assertNotEqual(one, empty)
            (p / "0001-fix.patch").write_text("two")
            self.assertNotEqual(d.patch_hash(p), one)


class RecipeHashTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patches = self.root / "patches"
        self.patches.mkdir()
        (self.root / "image" / "profile.d").mkdir(parents=True)
        (self.root / "image" / "Dockerfile.alpine").write_text("FROM alpine")
        (self.root / "image" / "profile.d" / "hermes.sh").write_text("a")
        self.cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def test_recipe_content_changes_the_hash(self):
        recipe = ("image/Dockerfile.alpine",)
        before = d.patch_hash(self.patches, recipe)
        self.assertNotEqual(before, d.patch_hash(self.patches))
        (self.root / "image" / "Dockerfile.alpine").write_text("FROM alpine:3")
        self.assertNotEqual(d.patch_hash(self.patches, recipe), before)

    def test_file_outside_the_recipe_is_ignored(self):
        recipe = ("image/Dockerfile.alpine", "image/profile.d")
        before = d.patch_hash(self.patches, recipe)
        (self.root / "tests").mkdir()
        (self.root / "tests" / "x.py").write_text("x")
        self.assertEqual(d.patch_hash(self.patches, recipe), before)

    def test_directory_entry_includes_nested_files_in_any_order(self):
        nested = self.root / "image" / "profile.d" / "sub"
        nested.mkdir()
        (nested / "deep.sh").write_text("1")
        recipe = ("image/Dockerfile.alpine", "image/profile.d")
        before = d.patch_hash(self.patches, recipe)
        self.assertEqual(d.patch_hash(self.patches, recipe[::-1]), before)
        (nested / "deep.sh").write_text("2")
        self.assertNotEqual(d.patch_hash(self.patches, recipe), before)

    def test_missing_recipe_path_fails(self):
        with self.assertRaises(FileNotFoundError):
            d.patch_hash(self.patches, ("image/nope",))

    def test_decide_builds_when_the_recipe_changed(self):
        recipe = ("image/Dockerfile.alpine",)
        old = d.decide("ghcr.io/o/h", self.patches, recipe=recipe, fetch=release(),
                       exists=lambda ref: False)
        (self.root / "image" / "Dockerfile.alpine").write_text("FROM alpine:3")
        published = {f"ghcr.io/o/h:{old['build_tag']}"}
        r = d.decide("ghcr.io/o/h", self.patches, recipe=recipe, fetch=release(),
                     exists=lambda ref: ref in published)
        self.assertTrue(r["build"])
        self.assertNotEqual(r["build_tag"], old["build_tag"])


class LatestReleaseTest(unittest.TestCase):
    def test_returns_the_stable_tag(self):
        self.assertEqual(d.latest_release(release("v0.22.2")), "v0.22.2")

    def test_rejects_draft_and_prerelease(self):
        with self.assertRaises(RuntimeError):
            d.latest_release(release(draft=True))
        with self.assertRaises(RuntimeError):
            d.latest_release(release(prerelease=True))

    def test_upstream_unreachable_raises(self):
        def down(url):
            raise urllib.error.URLError("unreachable")
        with self.assertRaises(urllib.error.URLError):
            d.latest_release(down)


class DecideTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = Path(self.tmp.name)
        self.hash = d.patch_hash(self.patches)
        self.seen = []

    def tearDown(self):
        self.tmp.cleanup()

    def exists_if(self, present):
        def exists(ref):
            self.seen.append(ref)
            return present
        return exists

    def test_new_release_builds_and_is_latest(self):
        r = d.decide("ghcr.io/o/h", self.patches, fetch=release("v0.22.2"), exists=self.exists_if(False))
        self.assertEqual(r, {"version": "v0.22.2", "patch_hash": self.hash,
                             "build_tag": f"v0.22.2-p{self.hash}", "build": True, "is_latest": True})
        self.assertEqual(self.seen, [f"ghcr.io/o/h:v0.22.2-p{self.hash}"])

    def test_already_built_is_skipped(self):
        r = d.decide("ghcr.io/o/h", self.patches, fetch=release(), exists=self.exists_if(True))
        self.assertFalse(r["build"])

    def test_force_rebuilds(self):
        r = d.decide("ghcr.io/o/h", self.patches, force=True, fetch=release(), exists=self.exists_if(True))
        self.assertTrue(r["build"])

    def test_an_older_tag_is_not_latest(self):
        r = d.decide("ghcr.io/o/h", self.patches, tag="v0.21.7", fetch=release("v0.22.2"),
                     exists=self.exists_if(False))
        self.assertEqual(r["version"], "v0.21.7")
        self.assertFalse(r["is_latest"])


if __name__ == "__main__":
    unittest.main()
