# Alpine Image Variants Implementation Plan

> Execute this plan task by task, with a review after each. Steps use checkbox (`- [ ]`) syntax
> for tracking.

**Goal:** Publish a `gateway` variant of `ghcr.io/oonid/hermes-agent` (about 0.7 GB on the phone,
about 265 MB to download, amd64 build) next to the unchanged full image, from the same release and
recipe.

**Architecture:** `image/Dockerfile.alpine` gains `ARG VARIANT=full`; the installer's `RUN` ends
with `image/slim.sh "$VARIANT"` from a read-only bind mount (no-op for `full`). `image/smoke.sh`
adds gateway, `pm doctor` and bytecode checks for every variant. `image/detect_release.py` reports
which variants are missing; the workflow builds those in a matrix and tags them with a suffix.

**Tech Stack:** Docker Buildx, POSIX shell/bash, Python 3 (`unittest`), GitHub Actions, GHCR.

**Design:** `docs/design/alpine-image-variants.md`.

## Global Constraints

- Repository: a clone of `oonid/hermes-agent`, branch `android`. Commands run from its root.
- Variants: `full` (today's image, unchanged) and `gateway`. `slim.sh` exits 2 on any other name.
- Tags: `full` keeps `<version>`, `<version>-alpine<x.y>`, `latest` (upstream's current release only)
  and `<version>-p<hash>`; `gateway` gets `<version>-gateway`, `<version>-gateway-alpine<x.y>`,
  `gateway` (upstream's current release only) and `<version>-p<hash>-gateway`.
- `gateway` keeps a stripped Node (no headers), removes the checkout's `.git`, and precompiles
  bytecode with `--invalidation-mode checked-hash`. It does not trim the venv's `workspace/` and
  does not remove `nemo_relay`.
- The cuts run in the same `RUN` as `install.sh`.
- The build hash covers `patches/*.patch`, `image/Dockerfile.alpine`, `image/profile.d/` and
  `image/slim.sh`.
- Every check in `image/smoke.sh` runs with `docker run --network none`.
- `image/build.sh <src-dir> <version> <patch-hash> <variant> <platform> <image-ref>...`;
  `image/smoke.sh <image-ref> <version>` (unchanged).
- Commits: subject plus a body wrapped at 72 columns or fewer; no trailers; no local paths or
  device identifiers.
- Ask the user before any push. The provider key goes on the phone only with the user's go-ahead
  and is removed afterwards.

## File Structure

```
image/slim.sh                      # new: the cuts per variant
image/Dockerfile.alpine            # ARG VARIANT, bind-mounted slim.sh, variant label
image/build.sh                     # <variant> argument
image/smoke.sh                     # gateway, pm doctor and bytecode checks
image/detect_release.py            # RECIPE += slim.sh; variants to build
image/tests/test_slim.py           # new: slim.sh argument handling
image/tests/test_detect_release.py # variants tests
.github/workflows/alpine-image.yml  # build matrix over the variants to build
README.md                          # variants
docs/design/alpine-image-variants.md  # §6 wording, §9 results
```

---

### Task 1: The slim script and the variant build

**Files:**
- Create: `image/slim.sh`, `image/tests/test_slim.py`
- Modify: `image/Dockerfile.alpine`, `image/build.sh`, `image/detect_release.py` (`RECIPE`)

**Interfaces:**
- Produces: `image/slim.sh <full|gateway>`; `image/build.sh <src-dir> <version> <patch-hash>
  <variant> <platform> <image-ref>...`; label `io.github.oonid.hermes.variant`.

- [ ] **Step 1: Write the failing tests** — `image/tests/test_slim.py`:

```python
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
```

- [ ] **Step 2: Run them to see them fail**

Run: `python3 -m unittest discover -s image/tests -p 'test_slim.py' -v`
Expected: FAIL (`slim.sh` does not exist; bash exits 127).

- [ ] **Step 3: Write `image/slim.sh`** (mode 100755):

```bash
#!/usr/bin/env bash
set -euo pipefail

case "${1:-}" in
    full) exit 0 ;;
    gateway) ;;
    *) echo "usage: $0 <full|gateway>" >&2; exit 2 ;;
esac

H=/root/.hermes
C=$H/hermes-agent
T=$H/tools
PY=$(ls -d "$T"/python-*/bin/python3)
SP=$(ls -d "$H"/installs/*/environments/*/venv/lib/python3.*/site-packages)

apk add --no-cache --virtual .slim binutils >/dev/null
find "$T"/python-* "$T"/node-* "$T"/uv-* "$T"/ripgrep-* "$SP" -type f \
    \( -name '*.so' -o -name '*.so.*' -o -perm -u+x \) \
    -exec sh -c 'for f; do head -c4 "$f" | grep -q ELF && strip --strip-unneeded "$f"; done' sh {} +
apk del .slim >/dev/null

rm -rf "$T"/node-*/include

HERMES_HOME=$H /usr/local/bin/hermes pm gc >/dev/null
rm -rf /root/.local/share/uv/python

find "$C" -name node_modules -type d -prune -exec rm -rf {} +

cd "$C"
rm -rf tests tests-js apps/desktop evals contributors .github
find website -mindepth 1 -maxdepth 1 ! -name static -exec rm -rf {} +
find website/static -mindepth 1 -maxdepth 1 ! -name api -exec rm -rf {} +

cd "$SP/googleapiclient/discovery_cache/documents"
ls | grep -vE '^(gmail\.v1|calendar\.v3|drive\.v3|docs\.v1|sheets\.v4|people\.v1|chat\.v1)\.json$' \
    | xargs rm -f

"$PY" -I -c 'import sys; sys.path.insert(0, "/root/.hermes/hermes-agent")
from pathlib import Path
from pm.lock import Facts
Facts(Path("/root/.hermes/tools/facts.json"), strict=True).refresh_digests(Path("/root/.hermes/tools"))'

rm -rf "$C/.git"

cd "$C"
"$PY" -I -m compileall -q -j0 --invalidation-mode checked-hash -l . >/dev/null
"$PY" -I -m compileall -q -j0 --invalidation-mode checked-hash \
    acp_adapter agent cron gateway hermes_cli hermes_platform plugins pm providers tools tui_gateway >/dev/null
"$PY" -I -m compileall -q -j0 --invalidation-mode checked-hash -x '/(test|tests|idlelib|tkinter|turtledemo)/' \
    "$(dirname "$(dirname "$PY")")"/lib/python3.* >/dev/null
"$PY" -I -m compileall -q -f -j0 --invalidation-mode checked-hash "$SP" >/dev/null

rm -rf /root/.cache /root/.npm /tmp/*
```

If a `compileall` run exits non-zero because of a file that cannot compile, find the file and say
so in the report. Do not hide the failure with `|| true`.

- [ ] **Step 4: Run the tests to see them pass**

Run: `python3 -m unittest discover -s image/tests -v`
Expected: all pass (17 earlier tests plus 3 new ones).

- [ ] **Step 5: Wire the variant into the build**

In `image/Dockerfile.alpine`:
- Add `ARG VARIANT=full` after `ARG PATCH_HASH`.
- Add a second bind mount to the installer's `RUN`:
  `--mount=type=bind,source=slim.sh,target=/src/slim.sh`.
- End that `RUN` chain with `&& bash /src/slim.sh "${VARIANT}"`, after the existing `rm -rf`.
- Add `io.github.oonid.hermes.variant="${VARIANT}"` to the `LABEL` list.

In `image/build.sh`, take the variant as the fourth argument and pass it on:

```bash
if [ $# -lt 6 ]; then
    echo "usage: $0 <src-dir> <version> <patch-hash> <variant> <platform> <image-ref>..." >&2
    exit 2
fi
src=$(cd "$1" && pwd) version=$2 phash=$3 variant=$4 platform=$5
shift 5
```

Add `--build-arg VARIANT="$variant" \` next to the other build arguments.

In `image/detect_release.py`, set
`RECIPE = ("image/Dockerfile.alpine", "image/profile.d", "image/slim.sh")`.

- [ ] **Step 6: Build both variants and compare** (local platform `linux/amd64`):

```bash
image/prepare.sh https://github.com/NousResearch/hermes-agent.git v0.22.2 patches work/src
image/build.sh work/src v0.22.2 local full linux/amd64 hermes-alpine:full
image/build.sh work/src v0.22.2 local gateway linux/amd64 hermes-alpine:gateway
image/smoke.sh hermes-alpine:full v0.22.2
image/smoke.sh hermes-alpine:gateway v0.22.2
docker image ls hermes-alpine
```

Expected:
- Both builds exit 0, and both smoke runs print `SMOKE OK`.
- `full` has the same file list (path and size) as `hermes-alpine:test`, the local build of the
  recipe before this task. To compare, use `docker create` and
  `docker export <id> | tar -tv | awk '{print $3, $6}' | sort` on each image, then `diff`. Report
  any differences.
- `gateway` is about 0.7 GB.
- In `gateway`:
  - `hermes --version` works;
  - `ls /root/.hermes/hermes-agent/.git` fails;
  - `ls /root/.hermes/tools/node-*/include` fails;
  - there is no `node_modules` under the checkout;
  - `hermes pm doctor` reports no problem.

Record the sizes from `docker image ls`, and the compressed size from
`docker save hermes-alpine:gateway | gzip -c | wc -c`.

- [ ] **Step 7: Commit**

```bash
git add image/slim.sh image/tests/test_slim.py image/Dockerfile.alpine image/build.sh image/detect_release.py
git commit -m "feat: build a slim gateway variant of the image" -m "image/slim.sh strips the managed runtimes, drops build tooling,
duplicate Python, tests, docs and the checkout's .git, and precompiles
bytecode; it runs in the installer's step from a bind mount and does
nothing for the full variant. build.sh takes the variant, the image is
labelled with it, and the build hash covers the script."
```

---

### Task 2: Smoke-test the gateway, pm doctor and bytecode

**Files:**
- Modify: `image/smoke.sh`

**Interfaces:**
- Consumes: the images `hermes-alpine:full` and `hermes-alpine:gateway` from Task 1.
- Produces: `image/smoke.sh <image-ref> <version>` with the extra checks, used by CI.

- [ ] **Step 1: Add the checks** before the final `echo "SMOKE OK: $out"`:

```bash
gw=$(run 'key=$(head -c16 /dev/urandom | od -An -tx1 | tr -d " \n")
printf "API_SERVER_ENABLED=true\nAPI_SERVER_KEY=%s\n" "$key" > /root/.hermes/.env
HERMES_HOME=/root/.hermes hermes gateway run >/tmp/gw.log 2>&1 &
for i in $(seq 1 90); do curl -fsS -m 2 http://127.0.0.1:8642/health && break; sleep 1; done
echo; hermes gateway status 2>&1' 2>&1 || true)
grep -q '"status": "ok"' <<<"$gw" || fail "the gateway API did not answer /health: $gw"
grep -q "default-profile multiplexer" <<<"$gw" || fail "the gateway does not serve the profile: $gw"

doctor=$(run 'hermes pm doctor 2>&1') || fail "hermes pm doctor failed: $doctor"
if grep -q "✗" <<<"$doctor"; then fail "hermes pm doctor found problems: $doctor"; fi

run 'hermes --version >/dev/null 2>&1; touch /tmp/mark; sleep 1; hermes --version >/dev/null 2>&1
test -z "$(find /root/.hermes/hermes-agent -name "*.pyc" -newer /tmp/mark | head -1)"' \
    || fail "a second run rewrote bytecode in the checkout"
```

Before relying on the `hermes pm doctor` check, find out how a problem shows in its exit code and
its output (`git show v0.22.2:pm/` in upstream; or run it on a broken image, Step 2). Adjust the
two lines to match, and say what you found.

- [ ] **Step 2: Prove each new check fails on a broken image**

Make throwaway images from `hermes-alpine:gateway` with `docker run … sh -c '<break>'` followed by
`docker commit`, run `image/smoke.sh` on each, then delete them:

| Break | Expected smoke failure |
|-------|------------------------|
| `rm /root/.hermes/hermes-agent/gateway/platforms/api_server.py` | the gateway API did not answer |
| `strip --strip-all` on the node binary without refreshing digests (install binutils first) | pm doctor found problems |
| `find /root/.hermes/hermes-agent -name "*.pyc" -delete` | a second run rewrote bytecode |

- [ ] **Step 3: Run it on both real images**

Run: `image/smoke.sh hermes-alpine:full v0.22.2 && image/smoke.sh hermes-alpine:gateway v0.22.2`
Expected: `SMOKE OK` twice. If `full` fails the bytecode check, report it with the files written:
upstream's image has no precompiled bytecode. Do not weaken the check for `gateway`.

- [ ] **Step 4: Commit**

```bash
git add image/smoke.sh
git commit -m "test: smoke-test the gateway, pm doctor and bytecode" -m "Every variant must start the gateway from the root home and serve the
profile, pass hermes pm doctor (stale tool digests after stripping),
and not rewrite bytecode in the checkout on a second run."
```

---

### Task 3: Build the missing variants in CI, and document them

**Files:**
- Modify: `image/detect_release.py`, `image/tests/test_detect_release.py`,
  `.github/workflows/alpine-image.yml`, `README.md`, `docs/design/alpine-image-variants.md` (§6)

**Interfaces:**
- Consumes: `image/build.sh … <variant> …` (Task 1), `image/smoke.sh` (Task 2).
- Produces: the detect output `variants` (a compact JSON list, e.g. `["full","gateway"]`), with
  `build=true` exactly when it is not empty.

- [ ] **Step 1: Write the failing tests** in `image/tests/test_detect_release.py`. Use the
  existing `fetch`/`exists` fakes in that file's `decide` tests:

```python
    def test_variant_tag(self):
        self.assertEqual(d.variant_tag("v1-pabc", "full"), "v1-pabc")
        self.assertEqual(d.variant_tag("v1-pabc", "gateway"), "v1-pabc-gateway")

    def test_only_missing_variants_are_built(self):
        published = {f"img:v0.22.2-p{self.hash}"}
        r = d.decide("img", self.patches, fetch=self.fetch, exists=published.__contains__)
        self.assertEqual(r["variants"], ["gateway"])
        self.assertTrue(r["build"])

    def test_nothing_to_build_when_every_variant_exists(self):
        r = d.decide("img", self.patches, fetch=self.fetch, exists=lambda ref: True)
        self.assertEqual(r["variants"], [])
        self.assertFalse(r["build"])

    def test_force_builds_every_variant(self):
        r = d.decide("img", self.patches, force=True, fetch=self.fetch, exists=lambda ref: True)
        self.assertEqual(r["variants"], ["full", "gateway"])
```

Adapt `self.fetch` and `self.hash` to the names the existing fixture uses. Update the existing
`decide` tests that compare the whole result dict to include `"variants"`. Add a `main` test that
the printed line is `variants=["full","gateway"]` (compact JSON) when nothing exists.

- [ ] **Step 2: Run them to see them fail**

Run: `python3 -m unittest discover -s image/tests -p 'test_detect_release.py' -v`
Expected: FAIL (`variant_tag` and the `variants` key are missing).

- [ ] **Step 3: Implement** in `image/detect_release.py`:

```python
VARIANTS = ("full", "gateway")


def variant_tag(build_tag, variant):
    return build_tag if variant == "full" else f"{build_tag}-{variant}"
```

In `decide`, replace the single `build` computation with:

```python
    has = exists or image_exists
    variants = [v for v in VARIANTS if force or not has(f"{image}:{variant_tag(build_tag, v)}")]
    return {"version": version, "patch_hash": phash, "build_tag": build_tag,
            "build": bool(variants), "variants": variants, "is_latest": version == latest}
```

In `main`, print a list value as `json.dumps(value, separators=(",", ":"))`, keeping booleans
lowercase as now.

- [ ] **Step 4: Run the tests to see them pass**

Run: `python3 -m unittest discover -s image/tests -v`
Expected: all pass.

- [ ] **Step 5: Build a matrix in the workflow** (`.github/workflows/alpine-image.yml`):
- `detect` outputs gain `variants: ${{ steps.detect.outputs.variants }}`.
- `build` gets:

```yaml
    strategy:
      fail-fast: false
      matrix:
        variant: ${{ fromJSON(needs.detect.outputs.variants) }}
    env:
      VARIANT: ${{ matrix.variant }}
```

  Keep the existing `env` keys next to `VARIANT`.
- Before the Build step, add a step that sets the suffix:

```yaml
      - name: Variant suffix
        run: |
          if [ "$VARIANT" = full ]; then echo "SUFFIX=" >> "$GITHUB_ENV"; else echo "SUFFIX=-$VARIANT" >> "$GITHUB_ENV"; fi
```

- Build: `image/build.sh work/src "$VERSION" "$PATCH_HASH" "$VARIANT" linux/arm64 "$IMAGE:$BUILD_TAG$SUFFIX"`.
- Smoke: `image/smoke.sh "$IMAGE:$BUILD_TAG$SUFFIX" "$VERSION"`.
- Publish, with `ref="$IMAGE:$BUILD_TAG$SUFFIX"` used everywhere `"$IMAGE:$BUILD_TAG"` is now:

```bash
          tags=("$BUILD_TAG$SUFFIX" "$VERSION$SUFFIX" "$VERSION$SUFFIX-alpine$alpine")
          if [ "$IS_LATEST" = "true" ]; then
            if [ "$VARIANT" = full ]; then tags+=(latest); else tags+=("$VARIANT"); fi
          fi
```

- In the summary heading, use `echo "## $IMAGE ($VARIANT)"`.
- Lint: `docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:1.7.7 -color`. Expected: no
  findings.

- [ ] **Step 6: Document the variants**

In `README.md`, change "## The image" so it lists both variants with their tags. Add this table
after the tags bullet:

```markdown
| Variant | Tags | On the phone / download | Works | Not included |
|---------|------|-------------------------|-------|--------------|
| full | `<version>`, `<version>-alpine<x.y>`, `latest` | 1.7 GB / 622 MB | everything upstream installs | browser automation, computer use |
| gateway | `<version>-gateway`, `<version>-gateway-alpine<x.y>`, `gateway` | ~0.7 GB / ~265 MB (amd64 build) | the gateway and its API, every messaging platform, cron, `hermes` and `hermes -z`, the prebuilt TUI and dashboard | rebuilding the TUI or dashboard from source, the checkout's git history, debug symbols, Google APIs beyond the seven Hermes uses, tests |
```

- Fill in the measured sizes from Task 1 in place of the estimates.
- In "Use it with oonid/pr", say that `ghcr.io/oonid/hermes-agent:gateway` is the smaller choice.
- Update the local build lines to `image/build.sh work/src v0.22.2 local full linux/amd64 hermes-alpine:test`,
  adding a `gateway` example.
- Replace "Design: …" with links to both designs and both plans.

In `docs/design/alpine-image-variants.md` §6, replace the "already built" bullet with:
"The 'already built' check stays per release and build hash, and builds only the variants whose
immutable tag is missing, so a variant that failed is retried and a published one is never
rebuilt unless forced."

- [ ] **Step 7: Commit**

```bash
git add image/detect_release.py image/tests/test_detect_release.py .github/workflows/alpine-image.yml README.md docs/design/alpine-image-variants.md
git commit -m "ci: build and publish each missing image variant" -m "Detect reports the variants whose immutable tag is missing; the build
job runs once per variant on the arm64 runner and publishes each with
its tag suffix. The README lists what each variant contains."
```

---

### Task 4: Publish (with the user)

**Files:** none.

- [ ] **Step 1: Ask the user before pushing.** Show `git log --oneline origin/android..android`.
- [ ] **Step 2: Push:** `git push origin android`. The push starts the workflow.
- [ ] **Step 3: Watch the run:** `gh run list -R oonid/hermes-agent --workflow alpine-image.yml --limit 1`,
  then `gh run watch -R oonid/hermes-agent <id> --exit-status`.
  - Expected: detect reports `variants=["full","gateway"]`, because the recipe changed and so did
    the hash. Both builds pass their smoke tests and publish.
  - On failure, read `gh run view --log-failed`, fix it in a new commit, and ask before pushing
    again.
- [ ] **Step 4: Verify an anonymous pull and the sizes:**

```bash
D=$(mktemp -d); DOCKER_CONFIG=$D docker manifest inspect ghcr.io/oonid/hermes-agent:gateway \
  | python3 -c 'import json,sys; m=json.load(sys.stdin); print(sum(l["size"] for l in m["layers"]))'; rm -rf "$D"
```

  Expected: a number, in bytes, around 265 MB (amd64 build), with no authentication error.
- [ ] **Step 5: Verify the no-op run:** `gh workflow run alpine-image.yml -R oonid/hermes-agent --ref android`.
  Expected: detect reports `variants=[]` and `build=false`, and the build job is skipped.

---

### Task 5: Validate the gateway variant on the phone

**Files:**
- Modify: `docs/design/alpine-image-variants.md` (§9)

Same method as `docs/design/alpine-image.md` §11. Drive the oonid/pr app with `adb`. Type in the
terminal with key events, and read results from files in the container through
`run-as id.or.oo.pr`.

- [ ] **Step 1: Install:** in oonid/pr, use Custom OCI image `ghcr.io/oonid/hermes-agent:<version>-gateway`
  with alias `hermes-gw`.
  - Time it from Install to "Completed".
  - Record the size: `adb shell run-as id.or.oo.pr du -sh files/usr/var/lib/pr/containers/hermes-gw`.
  - Record which layers were downloaded.
- [ ] **Step 2: First run:**
  - `HERMES_HOME` is the profile, and the profile is empty.
  - `hermes --version` works with no dependency sync; record the first and second times.
  - `hermes pm doctor` is clean.
- [ ] **Step 3: Gateway check.** Ask the user before putting the provider key on the phone.
  - Provider: a local OpenAI-compatible proxy reached through `adb reverse`, configured in the
    profile's `config.yaml` and `.env`.
  - Listener settings go in `/root/.hermes/.env`. Start the gateway with
    `HERMES_HOME=/root/.hermes hermes gateway run`.
  - Send two chat requests to `/p/android/v1` through `adb forward tcp:18642 tcp:8642`.
  - With the gateway running, `hermes -z "Reply with the single word OK"` must answer.
  - End the session; the gateway must stop cleanly.
- [ ] **Step 3b: More checks.**
  - `hermes --tui` shows its first screen.
  - `hermes dashboard` serves `curl http://127.0.0.1:9119/`.
  - The mtime check: set the file time of every `*.py` under the checkout, `tools` and `installs`
    to an old date, run `hermes --version` once, and confirm no `*.pyc` was written.
  - Compare the first and second `hermes --version` times with the full image's 10.2 s and 7.7 s.
- [ ] **Step 4: Clean up:**
  - remove the keys and every test file;
  - remove the `adb reverse` and `adb forward` rules;
  - check that no file on the phone contains the provider key;
  - remove `hermes-gw` if the user agrees.
- [ ] **Step 5: Record and commit.** Write §9 of `docs/design/alpine-image-variants.md`: install
  time, download and size against the full image (99 s, 618 MB, 1.7 GB), first-run times, and the
  gateway check. Set the status line to "implemented and validated on a phone (§9)".

```bash
git add docs/design/alpine-image-variants.md
git commit -m "docs: record the gateway variant's validation on a phone" -m "<install time, download and size against the full image; first run; gateway check>"
```

  Ask the user before pushing it.

## As executed

Deviations from the plan above (the code blocks stay as originally planned):

- The strip loop skips non-ELF files and aborts on a strip failure.
- `slim.sh` also clears `/var/cache/apk`.
- `compileall` is forced (`-f`) everywhere, including the venv's `pm-runtime`, so the bytecode
  stays valid when an extractor does not keep file times.
- The smoke gateway check writes a profile `.env` (an empty profile is not served), uses
  `curl -fs`, and judges `pm doctor` by its exit code.
- The smoke bytecode check is variant-aware: `full` runs twice, the other variants run once, after
  the file time of every source has been set to an old date.
- The `pm doctor` break in Task 2 appends a byte to `node` (stripping an already stripped binary
  changes nothing).
