# Alpine Hermes Image Implementation Plan

> Execute this plan task by task, with a review after each. Steps use checkbox (`- [ ]`) syntax
> for tracking.

**Goal:** Publish `ghcr.io/oonid/hermes-agent`, an arm64 Alpine image with Hermes preinstalled,
rebuilt automatically for each upstream stable release with this fork's patch series.

**Architecture:** The orphan `android` branch of the fork holds a release-detection script, a
prepare script (clone the upstream tag, apply `patches/`), a build script, a Dockerfile, a smoke
test and a GitHub Actions workflow. The workflow detects a new upstream release daily, builds
natively on GitHub's arm64 runner, smoke-tests with no network, then pushes the tags. User data is
a Hermes profile that shares the root's baked-in dependencies.

**Tech Stack:** Bash, Python 3 standard library (`unittest`, `urllib`), Docker Buildx, GitHub
Actions, GHCR.

**Design:** `docs/design/alpine-image.md` (read it first).

## Global Constraints

- Repository: a clone of `oonid/hermes-agent`, branch `android` (orphan; only our additions).
- Image: `ghcr.io/oonid/hermes-agent`; platform `linux/arm64` in CI (local test builds may use
  `linux/amd64`).
- Upstream: `https://github.com/NousResearch/hermes-agent.git`; "stable release" = GitHub
  `releases/latest` (not draft, not prerelease).
- Base: `alpine:3.24@sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6`.
- Install: `HERMES_HOME=/root/.hermes`, checkout `/root/.hermes/hermes-agent`, flags
  `--non-interactive --skip-browser --skip-computer-use`.
- User data: `HERMES_HOME=/root/.hermes/profiles/android`, empty in the image.
- Tags: immutable `<version>-p<hash>`, plus `<version>`, `<version>-alpine<x.y>`, and `latest`
  only when the version is upstream's current latest release.
- Actions pinned to SHAs: `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1` (v7.0.1),
  `docker/login-action@dbcb813823bdd20940b903addbd779551569679f` (v4.6.0).
- No secrets, keys or personal config in the image, the repository, commits or logs.
- Commits: subject plus a body wrapped at 72 columns; no trailers or tool attribution, no device
  identifiers.
- Pushing and GitHub settings are outward-facing: ask the user before pushing, and leave the
  settings in Task 5 to the user.

## File Structure

```
image/
  detect_release.py        # decide what to build: upstream version, patch hash, build tag, flags
  prepare.sh               # clone the upstream tag, apply patches/, branch image-build
  build.sh                 # docker buildx build with the build args and labels
  smoke.sh                 # offline checks on a built image
  Dockerfile.alpine        # the image
  profile.d/hermes.sh      # login-shell environment (HERMES_HOME, PATH)
  tests/test_detect_release.py
  tests/test_prepare.py
patches/README.md          # how the patch series works (series starts empty)
.github/workflows/alpine-image.yml
.gitignore                 # work/, __pycache__/
README.md
docs/design/alpine-image.md   (exists)
docs/plans/alpine-image.md    (this file)
```

---

### Task 1: Release detection

**Files:**
- Create: `image/detect_release.py`
- Create: `image/tests/test_detect_release.py`

**Interfaces:**
- Produces: `python3 image/detect_release.py --image IMAGE [--patches DIR] [--tag TAG] [--force]`
  prints `key=value` lines (and appends them to `$GITHUB_OUTPUT` when set): `version`,
  `patch_hash` (8 hex chars), `build_tag` (`<version>-p<patch_hash>`), `build` (`true`/`false`),
  `is_latest` (`true`/`false`). Exits non-zero if upstream cannot be read.
- Produces: `patch_hash(Path) -> str`, `latest_release(fetch) -> str`,
  `decide(image, patch_dir, tag=None, force=False, fetch=None, exists=None) -> dict`.

- [ ] **Step 1: Write the failing tests**

`image/tests/test_detect_release.py`:

```python
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
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `python3 -m unittest discover -s image/tests -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'detect_release'`.

- [ ] **Step 3: Implement**

`image/detect_release.py`:

```python
#!/usr/bin/env python3
"""Decide which upstream Hermes release to build and whether it is already published."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

UPSTREAM = "NousResearch/hermes-agent"


def patch_hash(patch_dir: Path) -> str:
    digest = hashlib.sha256()
    for patch in sorted(Path(patch_dir).glob("*.patch")):
        digest.update(patch.name.encode())
        digest.update(b"\0")
        digest.update(patch.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:8]


def _fetch_json(url):
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
        return json.load(response)


def latest_release(fetch=None) -> str:
    data = (fetch or _fetch_json)(f"https://api.github.com/repos/{UPSTREAM}/releases/latest")
    tag = data.get("tag_name")
    if not tag or data.get("draft") or data.get("prerelease"):
        raise RuntimeError(f"upstream has no stable latest release: {str(data)[:200]}")
    return tag


def image_exists(ref) -> bool:
    return subprocess.run(["docker", "manifest", "inspect", ref], capture_output=True).returncode == 0


def decide(image, patch_dir, tag=None, force=False, fetch=None, exists=None):
    latest = latest_release(fetch)
    version = tag or latest
    phash = patch_hash(patch_dir)
    build_tag = f"{version}-p{phash}"
    build = force or not (exists or image_exists)(f"{image}:{build_tag}")
    return {"version": version, "patch_hash": phash, "build_tag": build_tag,
            "build": build, "is_latest": version == latest}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--patches", default="patches")
    parser.add_argument("--tag", default="")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    result = decide(args.image, Path(args.patches), args.tag or None, args.force)
    lines = [f"{key}={str(value).lower() if isinstance(value, bool) else value}"
             for key, value in result.items()]
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `python3 -m unittest discover -s image/tests -v`
Expected: 9 tests, OK.

- [ ] **Step 5: Try it against real upstream**

Run: `mkdir -p patches && python3 image/detect_release.py --image ghcr.io/oonid/hermes-agent --patches patches`
Expected: `version=` the current upstream latest release (`v0.22.2` at planning time),
`build=true` (nothing is published yet), `is_latest=true`.

- [ ] **Step 6: Commit**

```bash
git add image/detect_release.py image/tests/test_detect_release.py
git commit -m "feat: detect which upstream release to build" -m "Reads upstream's latest stable release, hashes the patch series and
reports the immutable build tag, whether it is already published, and
whether the version is upstream's latest."
```

---

### Task 2: Prepare the patched checkout

**Files:**
- Create: `image/prepare.sh`
- Create: `image/tests/test_prepare.py`
- Create: `patches/README.md`
- Create: `.gitignore`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `image/prepare.sh <upstream-url> <tag> <patch-dir> <out-dir>`: a shallow clone of `<tag>`
  in `<out-dir>`, on a new branch `image-build`, with every `<patch-dir>/*.patch` applied in name
  order via `git am`, and `uploadpack.allowFilter` enabled so the installer can clone it over
  `file://` (later removed; see design §10). Prints the resulting commit SHA as its last line. Exits non-zero (after
  `git am --abort`) if a patch does not apply.

- [ ] **Step 1: Write the failing tests**

`image/tests/test_prepare.py`:

```python
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
        self.assertEqual(git(self.out, "config", "uploadpack.allowFilter"), "true")

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
```

`0002` is cut from the tag, so it conflicts after `0001`; the series must stop there.

- [ ] **Step 2: Run the tests and see them fail**

Run: `python3 -m unittest discover -s image/tests -p 'test_prepare.py' -v`
Expected: 3 failures (the script does not exist).

- [ ] **Step 3: Implement**

`image/prepare.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

if [ $# -ne 4 ]; then
    echo "usage: $0 <upstream-url> <tag> <patch-dir> <out-dir>" >&2
    exit 2
fi
url=$1 tag=$2 out=$4
patches=$(cd "$3" && pwd)

rm -rf "$out"
git clone --quiet --depth 1 --branch "$tag" "$url" "$out"
git -C "$out" checkout --quiet -b image-build
git -C "$out" config uploadpack.allowFilter true

shopt -s nullglob
series=("$patches"/*.patch)
if [ ${#series[@]} -gt 0 ]; then
    if ! git -C "$out" -c user.name="hermes image build" \
            -c user.email="hermes-image-build@users.noreply.github.com" \
            am --quiet "${series[@]}"; then
        git -C "$out" am --abort || true
        echo "a patch in $patches does not apply to $tag" >&2
        exit 1
    fi
fi
git -C "$out" rev-parse HEAD
```

`patches/README.md`:

```markdown
# Patches

Changes this fork applies on top of each upstream stable release before building the image.

- One `git format-patch` file per change, named `NNNN-short-description.patch`, applied in name
  order with `git am` by `image/prepare.sh`. Files that do not end in `.patch` are ignored.
- A patch that no longer applies fails the image build; nothing is published. Rebase it onto the
  new release (or drop it if upstream fixed the problem) and push.
- Delete a patch once its fix is in an upstream release.
- Changing this directory changes the patch hash, so the next run builds a new image.

The series starts empty: no change is needed yet to run Hermes under PRoot on the current release.
```

`.gitignore`:

```
work/
__pycache__/
```

Make the scripts executable: `chmod +x image/prepare.sh image/detect_release.py`.

- [ ] **Step 4: Run all tests and see them pass**

Run: `python3 -m unittest discover -s image/tests -v`
Expected: 12 tests, OK.

- [ ] **Step 5: Commit**

```bash
git add image/prepare.sh image/tests/test_prepare.py patches/README.md .gitignore
git commit -m "feat: prepare an upstream release with the patch series" -m "Clones the release tag shallowly, applies patches/ in order with git am
and branches it for the installer. A patch that does not apply stops
the build."
```

---

### Task 3: The image and its smoke test

Superseded during implementation: the image is built from a read-only bind mount of the prepared
`.git` (see design §10 and `image/Dockerfile.alpine`); the code is canonical.

This task is also the gate that proves the profile layout: if the smoke test shows a dependency
sync under the profile, or the profile gets its own `installs/`, **stop and report**; the design
must be revisited before anything else.

**Files:**
- Create: `image/Dockerfile.alpine`
- Create: `image/profile.d/hermes.sh`
- Create: `image/build.sh`
- Create: `image/smoke.sh`

**Interfaces:**
- Consumes: `image/prepare.sh` (Task 2), `patch_hash` (Task 1).
- Produces: `image/build.sh <src-dir> <version> <patch-hash> <platform> <image-ref>...` (builds and
  loads the image into the local Docker); `image/smoke.sh <image-ref> <version>` (exit 0 and a
  `SMOKE OK` line, or a `SMOKE FAIL: …` line and exit 1). The Dockerfile's
  `ARG ALPINE_VERSION=3.24` line is the single source for the `-alpine<x.y>` tag.

- [ ] **Step 1: Write the smoke test first**

`image/smoke.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

if [ $# -ne 2 ]; then
    echo "usage: $0 <image-ref> <version>" >&2
    exit 2
fi
image=$1 version=${2#v}
profile=/root/.hermes/profiles/android

run() { docker run --rm --network none "$image" sh -lc "$1"; }
fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }

[ "$(run 'echo "$HERMES_HOME"')" = "$profile" ] || fail "HERMES_HOME is not $profile in a login shell"
[ "$(run 'ls -A "$HERMES_HOME" | wc -l')" = 0 ] || fail "the profile directory is not empty"

out=$(run 'hermes --version 2>&1') || fail "hermes --version failed: $out"
grep -q -- "$version" <<<"$out" || fail "version $version not in: $out"
if grep -qiE "preparing the isolated hermes runtime|installing python dependencies|preparing dependencies" <<<"$out"; then
    fail "a profile run synced dependencies: $out"
fi

run 'hermes --version >/dev/null 2>&1; test ! -e "$HERMES_HOME/installs"' \
    || fail "the profile got its own dependency state"

leaks=$(run 'find /root /etc -xdev \( -path /root/.hermes/hermes-agent -o -path /root/.hermes/installs -o -path /root/.hermes/tools \) -prune -o \( -name .env -o -name auth.json \) -print 2>/dev/null' || true)
[ -z "$leaks" ] || fail "secret-like files in the image: $leaks"

echo "SMOKE OK: $out"
```

- [ ] **Step 2: Run it against a missing image and see it fail**

Run: `chmod +x image/smoke.sh && image/smoke.sh hermes-alpine:test v0.22.2; echo "exit=$?"`
Expected: a non-zero exit (Docker reports the image cannot be found).

- [ ] **Step 3: Write the image and the build script**

`image/profile.d/hermes.sh`:

```sh
export HERMES_HOME=/root/.hermes/profiles/android
case ":$PATH:" in
    *":/root/.local/bin:"*) ;;
    *) export PATH="/root/.local/bin:$PATH" ;;
esac
```

`image/Dockerfile.alpine`:

```dockerfile
# syntax=docker/dockerfile:1
ARG ALPINE_VERSION=3.24
ARG ALPINE_DIGEST=sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6
FROM alpine:${ALPINE_VERSION}@${ALPINE_DIGEST}

RUN apk add --no-cache bash curl git ca-certificates coreutils libstdc++

ARG HERMES_COMMIT
ARG HERMES_VERSION
ARG FORK_REVISION
ARG PATCH_HASH

COPY --from=src . /src/hermes
RUN HERMES_HOME=/root/.hermes HERMES_REPO_URL=file:///src/hermes \
        bash /src/hermes/scripts/install.sh --branch image-build --commit "${HERMES_COMMIT}" \
        --non-interactive --skip-browser --skip-computer-use \
    && export PATH="/root/.local/bin:${PATH}" \
    && ln -sf "$(command -v hermes)" /usr/local/bin/hermes \
    && mkdir -p /root/.hermes/profiles/android \
    && rm -rf /src/hermes /root/.cache /root/.npm /tmp/* /var/cache/apk/*

COPY profile.d/hermes.sh /etc/profile.d/hermes.sh
ENV HERMES_HOME=/root/.hermes/profiles/android

LABEL org.opencontainers.image.source="https://github.com/oonid/hermes-agent" \
      org.opencontainers.image.description="Alpine Linux with Hermes Agent preinstalled" \
      org.opencontainers.image.version="${HERMES_VERSION}" \
      org.opencontainers.image.revision="${FORK_REVISION}" \
      io.github.oonid.hermes.upstream-commit="${HERMES_COMMIT}" \
      io.github.oonid.hermes.patch-hash="${PATCH_HASH}"

CMD ["hermes"]
```

`image/build.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 5 ]; then
    echo "usage: $0 <src-dir> <version> <patch-hash> <platform> <image-ref>..." >&2
    exit 2
fi
src=$(cd "$1" && pwd) version=$2 phash=$3 platform=$4
shift 4
here=$(cd "$(dirname "$0")" && pwd)
commit=$(git -C "$src" rev-parse HEAD)
revision=$(git -C "$here" rev-parse HEAD 2>/dev/null || echo unknown)

tags=()
for ref in "$@"; do tags+=(-t "$ref"); done

docker buildx build --platform "$platform" --load \
    --build-context src="$src" \
    --build-arg HERMES_COMMIT="$commit" \
    --build-arg HERMES_VERSION="$version" \
    --build-arg FORK_REVISION="$revision" \
    --build-arg PATCH_HASH="$phash" \
    -f "$here/Dockerfile.alpine" "${tags[@]}" "$here"
```

Run `chmod +x image/build.sh image/smoke.sh`.

- [ ] **Step 4: Build v0.22.2 locally** (amd64 for speed; the profile behaviour does not depend on
  the architecture)

```bash
phash=$(python3 -c 'import sys; sys.path.insert(0, "image"); import detect_release as d; from pathlib import Path; print(d.patch_hash(Path("patches")))')
image/prepare.sh https://github.com/NousResearch/hermes-agent.git v0.22.2 patches work/src
image/build.sh work/src v0.22.2 "$phash" linux/amd64 hermes-alpine:test
```

Expected: the build finishes. If the installer stops on a missing Alpine package, add that package
to the `apk add` line, record why in the commit body, and rebuild. If the clone inside the
installer fails, report the installer's message (the `file://` source and `--branch image-build`
are the assumptions to check).

- [ ] **Step 5: Run the smoke test and see it pass**

Run: `image/smoke.sh hermes-alpine:test v0.22.2`
Expected: `SMOKE OK: …0.22.2…`. Any `SMOKE FAIL` about a dependency sync or `installs/` under the
profile means the profile layout does not hold: **stop and report it** with the full output.

- [ ] **Step 6: Record the size**

Run: `docker image inspect hermes-alpine:test --format '{{.Size}}' | numfmt --to=iec`
Note the size in the commit body.

- [ ] **Step 7: Commit**

```bash
git add image/Dockerfile.alpine image/profile.d/hermes.sh image/build.sh image/smoke.sh
git commit -m "feat: build an Alpine image with Hermes installed" -m "Hermes is installed by its own installer under the root /root/.hermes,
without the browser and computer-use tools, and user data is the empty
profile /root/.hermes/profiles/android, which reuses the root's
dependencies. The smoke test checks this offline, along with the
version and the absence of secrets. Local amd64 image size: <size>."
```

---

### Task 4: The workflow and the README

**Files:**
- Create: `.github/workflows/alpine-image.yml`
- Create: `README.md`

**Interfaces:**
- Consumes: `image/detect_release.py` outputs (`version`, `patch_hash`, `build_tag`, `build`,
  `is_latest`), `image/prepare.sh`, `image/build.sh`, `image/smoke.sh`, the Dockerfile's
  `ARG ALPINE_VERSION=` line.
- Produces: the published tags described in the Global Constraints.

- [ ] **Step 1: Write the workflow**

`.github/workflows/alpine-image.yml`:

```yaml
name: alpine-image

on:
  schedule:
    - cron: "17 3 * * *"
  workflow_dispatch:
    inputs:
      tag:
        description: "Upstream tag to build (default: the latest stable release)"
        required: false
        default: ""
      force:
        description: "Rebuild even if this release and patch series are already published"
        type: boolean
        default: false
  push:
    branches: [android]

permissions:
  contents: read
  packages: write

concurrency:
  group: alpine-image
  cancel-in-progress: false

env:
  IMAGE: ghcr.io/oonid/hermes-agent
  UPSTREAM_URL: https://github.com/NousResearch/hermes-agent.git

jobs:
  detect:
    runs-on: ubuntu-24.04
    outputs:
      version: ${{ steps.detect.outputs.version }}
      patch_hash: ${{ steps.detect.outputs.patch_hash }}
      build_tag: ${{ steps.detect.outputs.build_tag }}
      build: ${{ steps.detect.outputs.build }}
      is_latest: ${{ steps.detect.outputs.is_latest }}
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - name: Unit tests
        run: python3 -m unittest discover -s image/tests -v
      - uses: docker/login-action@dbcb813823bdd20940b903addbd779551569679f # v4.6.0
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Detect the release to build
        id: detect
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          TAG_INPUT: ${{ inputs.tag }}
          FORCE_INPUT: ${{ inputs.force }}
        run: |
          args=(--image "$IMAGE" --patches patches)
          if [ -n "$TAG_INPUT" ]; then args+=(--tag "$TAG_INPUT"); fi
          if [ "$FORCE_INPUT" = "true" ]; then args+=(--force); fi
          python3 image/detect_release.py "${args[@]}"

  build:
    needs: detect
    if: needs.detect.outputs.build == 'true'
    runs-on: ubuntu-24.04-arm
    env:
      VERSION: ${{ needs.detect.outputs.version }}
      PATCH_HASH: ${{ needs.detect.outputs.patch_hash }}
      BUILD_TAG: ${{ needs.detect.outputs.build_tag }}
      IS_LATEST: ${{ needs.detect.outputs.is_latest }}
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - name: Prepare the upstream release with the patch series
        run: image/prepare.sh "$UPSTREAM_URL" "$VERSION" patches work/src
      - name: Build
        run: image/build.sh work/src "$VERSION" "$PATCH_HASH" linux/arm64 "$IMAGE:$BUILD_TAG"
      - name: Smoke test
        run: image/smoke.sh "$IMAGE:$BUILD_TAG" "$VERSION"
      - uses: docker/login-action@dbcb813823bdd20940b903addbd779551569679f # v4.6.0
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Publish
        run: |
          alpine=$(sed -n 's/^ARG ALPINE_VERSION=//p' image/Dockerfile.alpine)
          tags=("$BUILD_TAG" "$VERSION" "$VERSION-alpine$alpine")
          if [ "$IS_LATEST" = "true" ]; then tags+=(latest); fi
          for tag in "${tags[@]}"; do
            docker tag "$IMAGE:$BUILD_TAG" "$IMAGE:$tag"
            docker push "$IMAGE:$tag"
          done
          digest=$(docker image inspect "$IMAGE:$BUILD_TAG" --format '{{index .RepoDigests 0}}')
          size=$(docker image inspect "$IMAGE:$BUILD_TAG" --format '{{.Size}}' | numfmt --to=iec)
          compressed=$(docker manifest inspect "$IMAGE:$BUILD_TAG" \
            | python3 -c 'import json,sys; m=json.load(sys.stdin); print(sum(l["size"] for l in m.get("layers", [])))' \
            | numfmt --to=iec)
          {
            echo "## $IMAGE"
            echo
            echo "- Upstream release: \`$VERSION\`"
            echo "- Patch series: \`$PATCH_HASH\` ($(ls patches/*.patch 2>/dev/null | wc -l) patches)"
            echo "- Tags: $(printf '`%s` ' "${tags[@]}")"
            echo "- Digest: \`$digest\`"
            echo "- Size: $size uncompressed, $compressed compressed"
          } >> "$GITHUB_STEP_SUMMARY"
```

- [ ] **Step 2: Lint the workflow**

Run: `docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:1.7.7 -color`
Expected: no findings. Fix any finding before going on.

- [ ] **Step 3: Write the README**

`README.md`:

```markdown
# Hermes Agent on Alpine for Android (PRoot)

This branch of `oonid/hermes-agent` builds `ghcr.io/oonid/hermes-agent`: Alpine Linux with Hermes
Agent preinstalled, for Android apps that run Linux containers under PRoot (no root, no VM). The
`main` branch mirrors upstream `NousResearch/hermes-agent` unchanged.

## The image

- Each upstream stable release, with the patches in `patches/` applied, built for `linux/arm64`.
- Tags: `<version>` (e.g. `v0.22.2`), `<version>-alpine<x.y>`, the immutable build
  `<version>-p<hash>` (the hash covers `patches/` and the image recipe, `image/Dockerfile.alpine`
  and `image/profile.d/`), and `latest` for upstream's current release.
- Hermes is installed by its own installer under `/root/.hermes`; browser automation and computer
  use are left out because they cannot run under PRoot on Android.
- Your data lives in the Hermes profile `/root/.hermes/profiles/android` (`HERMES_HOME`). It is
  empty in the image and reuses the image's dependencies, so an app can keep it outside the
  container and swap in a newer image without losing it.
- No keys or personal settings are in the image.

## Use it with oonid/pr

In the oonid/pr app, open **Custom OCI image**, enter `ghcr.io/oonid/hermes-agent:latest` with an
alias such as `hermes-img`, and install. Open the container, then configure a model provider in
`$HERMES_HOME/.env` and `$HERMES_HOME/config.yaml`, and run `hermes`.

The gateway is one per container, started from the root home; it serves the `android` profile
with the profile's settings (`hermes gateway run` inside the profile is refused with exit 78):

```sh
printf 'API_SERVER_ENABLED=true\nAPI_SERVER_KEY=<16+ characters>\n' > /root/.hermes/.env
HERMES_HOME=/root/.hermes hermes gateway run
```

The listener settings must be in `/root/.hermes/.env`: a gateway serving profiles ignores keys
passed as process environment. With an `API_SERVER_KEY` (16+ characters) also in
`$HERMES_HOME/.env`, the profile's OpenAI-compatible API is at
`http://127.0.0.1:8642/p/android/v1`.

Updating Hermes means installing a newer image; `hermes update` does not work inside the
container.

## How it is built

`.github/workflows/alpine-image.yml` checks upstream daily (and on a push to this branch or a
manual run). For a release and patch series not yet published it clones the release, applies
`patches/` (`image/prepare.sh`), builds `image/Dockerfile.alpine` on GitHub's arm64 runner
(`image/build.sh`), runs an offline smoke test (`image/smoke.sh`), and only then pushes.

Local build and test (any architecture; `linux/amd64` is fine on a PC):

    image/prepare.sh https://github.com/NousResearch/hermes-agent.git v0.22.2 patches work/src
    image/build.sh work/src v0.22.2 local linux/amd64 hermes-alpine:test
    image/smoke.sh hermes-alpine:test v0.22.2
    python3 -m unittest discover -s image/tests -v

Design: `docs/design/alpine-image.md`. Plan: `docs/plans/alpine-image.md`.
```

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/alpine-image.yml README.md
git commit -m "ci: build and publish the Alpine image for new upstream releases" -m "A daily, manual or push-triggered run detects a new upstream stable
release or patch series, builds it natively on the arm64 runner,
smoke-tests it offline and pushes the version, Alpine and immutable
build tags, plus latest for upstream's current release."
```

---

### Task 5: Publish (with the user)

**Files:** none.

- [ ] **Step 1: Ask the user before pushing.** Show `git log --oneline` of `android` and confirm.
- [ ] **Step 2: User enables Actions on the fork** (Actions tab: forks start with workflows
  disabled).
- [ ] **Step 3: Disable upstream's workflows** that would run on `main` pushes or "Sync fork":
  `gh workflow list -R oonid/hermes-agent`, then `gh workflow disable <id> -R oonid/hermes-agent`
  for each (or accept the noise; ask the user).
- [ ] **Step 4: Push `android` only** (SSH; the workflow file needs it):
  `git push -u origin android` (never `--all`). The push trigger runs the workflow right away.
- [ ] **Step 5: Watch the first run**:
  `gh run list -R oonid/hermes-agent --workflow alpine-image.yml --limit 1` then
  `gh run watch -R oonid/hermes-agent <id> --exit-status`.
  Expected: `detect` reports `build=true`; `build` passes the smoke test and pushes. On failure,
  read the log (`gh run view --log-failed`), fix in a new commit, and push again.
- [ ] **Step 6: Default branch to `android`** (user: Repository Settings → General → Default
  branch; scheduled runs need it, and so do manual runs from the Actions tab).
- [ ] **Step 7: Package to Public** (user: github.com/oonid → Packages → `hermes-agent` → Package
  settings → Change visibility; phones pull anonymously).
- [ ] **Step 8: Verify an anonymous pull works:**
  `docker logout ghcr.io; docker manifest inspect ghcr.io/oonid/hermes-agent:latest | head -5`
  Expected: a manifest, no authentication error.
- [ ] **Step 9: Verify the no-op run:** trigger a manual run
  (`gh workflow run alpine-image.yml -R oonid/hermes-agent --ref android`) and confirm `detect`
  reports `build=false` and the `build` job is skipped.

GitHub disables schedules in a public repository after 60 days without repository activity;
"Sync fork" commits keep it active.

---

### Task 6: Validate on the phone with oonid/pr

**Files:**
- Modify: `docs/design/alpine-image.md` (append `## 11. Validation Results`)

- [ ] **Step 1: Install the image** in the oonid/pr app: Custom OCI image
  `ghcr.io/oonid/hermes-agent:<version>` (the version just published), alias `hermes-img`. Time it
  from Install to "Done.", and note the container size
  (`adb shell run-as id.or.oo.pr du -sh files/usr/var/lib/pr/containers/hermes-img`).
- [ ] **Step 2: First run.** Open the container: `echo $HERMES_HOME` prints
  `/root/.hermes/profiles/android`; `hermes --version` prints the version with no dependency sync,
  and finishes within seconds.
- [ ] **Step 3: Gateway check** (ask the user before putting the provider key on the phone; remove
  it afterwards). As in oonid/pr PR #16: provider settings in the profile's `.env` and
  `config.yaml`, plus `API_SERVER_KEY` (16+ characters) in the profile's `.env`; the listener
  settings (`API_SERVER_ENABLED=true`, a root `API_SERVER_KEY`) in `/root/.hermes/.env`; the host
  gateway `HERMES_HOME=/root/.hermes hermes gateway run > /tmp/gw.log 2>&1 &`;
  at least two requests to `http://127.0.0.1:8642/p/android/v1` with the profile's key through
  `adb forward`; the sessions land under `$HERMES_HOME`; with the gateway running, `hermes -z "Reply with the single
  word OK"` in the same shell must connect and answer (this is the CLI-to-gateway case the earlier
  WebSocket import fix addressed); then End session must log a clean SIGTERM shutdown.
- [ ] **Step 4: If the CLI-to-gateway connection fails** with "Gateway connection failed", that is
  the cold WebSocket import problem: stop and report. Porting the fix to
  `hermes_cli/web_routers/chat_ws.py` as `patches/0001-….patch` becomes a separate task.
- [ ] **Step 5: Clean up**: remove the provider key and any `adb forward`; keep or remove
  `hermes-img` as the user prefers.
- [ ] **Step 6: Record and commit** the results (install time and size against the ~11-minute
  baseline, first-run time, gateway check results) in `docs/design/alpine-image.md` §11:

```bash
git add docs/design/alpine-image.md
git commit -m "docs: record the image's validation on a phone" -m "<install time and size, first run, gateway check results>"
git push origin android
```
