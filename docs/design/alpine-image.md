# Alpine Hermes Image

**Date:** 2026-10-19
**Status:** implemented; validation on a phone pending (§11)

## 1. Goal

Publish a public Alpine Linux OCI image with Hermes Agent preinstalled, rebuilt automatically for
each upstream stable release with this fork's patches, so an Android app running containers under
PRoot can set Hermes up with one download instead of installing it on the phone (about 11 minutes
in the earlier phone phase).

This is the first of two projects. The second, a dedicated Android app that pulls this image and
runs the Hermes gateway under PRoot (first-run setup, bind-mounting the data directory, background
sessions), gets its own design after this image is proven. Until then the image is validated with
the existing generic app, oonid/pr, through its Custom OCI image card.

## 2. Decisions

| Topic | Decision |
|-------|----------|
| Format and registry | Public OCI image on GHCR, `ghcr.io/oonid/hermes-agent`, pulled by pr-cli's existing OCI path (layer cache, sha256 checks, anonymous bearer-token pulls) |
| Contents | Alpine plus what Hermes's `install.sh` sets up by default; extras can be added later inside the container |
| What is tracked | Upstream (`NousResearch/hermes-agent`) stable releases |
| Code built | The upstream stable tag with this fork's patch series applied; a patch that no longer applies fails the build |
| User data | Outside the image: a Hermes profile, `HERMES_HOME=/root/.hermes/profiles/android`, empty in the image, that apps bind-mount; the profile shares the root's baked-in dependencies, so updating means installing a newer image while the data stays |
| Build approach | A Dockerfile built natively on GitHub's arm64 Linux runner by a scheduled workflow in the fork |
| Architectures | `linux/arm64` only (phones); amd64 later if needed |

## 3. Fork Layout

- **`main`** mirrors upstream unchanged. It is updated with GitHub's "Sync fork"; nothing of ours
  lives there, so syncing never conflicts.
- **`android`** is the fork's default branch (scheduled workflows run only on the default branch)
  and an orphan branch that holds only our additions:
  - `patches/` — our Hermes changes as a numbered `git format-patch` series (`0001-….patch`, …),
    applied in order with `git am`. A patch is deleted once its fix is in an upstream release.
  - `image/`: the Dockerfile, the build, prepare, detect and smoke scripts, their tests, and the
    files the Dockerfile copies.
  - `.gitignore`.
  - `.github/workflows/alpine-image.yml`.
  - `docs/design/`, `docs/plans/`, and `README.md` (what the image is and how apps use it).
- The series starts empty. Of the three local Hermes commits from the earlier phone phase, the
  plugin-loader race and the schema-reconcile cache are general fixes and go upstream as pull
  requests. The gateway WebSocket import fix targets code that upstream's release line does not
  have (v0.22.2 serves `/api/ws` from `hermes_cli/web_routers/chat_ws.py`); the device validation
  checks a CLI connection to the gateway, and the fix is ported as a patch only if that check
  fails.

## 4. Image Contents and Contract

- **Base:** `alpine` at a pinned version and digest (3.24 at design time), bumped deliberately in
  this branch.
- **Install:** the runtime packages `install.sh` requires on Alpine (bash, curl, git,
  ca-certificates, coreutils, libstdc++, plus any other package the installer reports missing
  during the first build, recorded in the Dockerfile); then `install.sh --non-interactive
  --skip-browser --skip-computer-use` with `HERMES_HOME=/root/.hermes` against the patched release
  checkout, so the checkout is `/root/.hermes/hermes-agent` and its dependency state is under the
  root `/root/.hermes`. Browser automation (Chromium) and computer use are skipped: they cannot run
  under PRoot on Android. `hermes` is on the PATH through `/usr/local/bin/hermes`; apk, uv, pip and
  npm caches are removed.
- **No secrets or personal configuration** in the image.
- **Data:** `HERMES_HOME=/root/.hermes/profiles/android`, an empty Hermes profile directory.
  Hermes keeps its dependency environment per data root (`<root>/installs/<key>`), and a profile
  resolves to its root (`/root/.hermes`), so runs under the profile reuse the dependencies baked
  into the image instead of syncing them on first use. Config, `.env`, sessions, memories and
  skills land in the profile. The image's `ENV` sets only `HERMES_HOME` (pr-cli writes it to
  `/etc/environment` at install); `/root/.local/bin` comes from `/etc/profile.d/hermes.sh`, and
  `hermes` is reachable without a login shell through `/usr/local/bin/hermes`.
- **User:** root (PRoot's fake root).
- **`CMD ["hermes"]`** for plain `docker run`; PRoot apps open `sh -l` and ignore it.
- **OCI labels:** `org.opencontainers.image.source`, `.version` (the upstream tag), `.revision`
  (the fork commit), and a label with the build hash (patch series plus image recipe), so an
  installed image states exactly what it contains.
- **Contract for apps:** `hermes` works in a login shell; user state lives only under
  `/root/.hermes/profiles/android`, which apps may bind-mount from outside; a model provider is
  configured through `$HERMES_HOME/.env` and `$HERMES_HOME/config.yaml`. First-run setup belongs
  to the app. `hermes update` is unsupported in the container: its origin points at the
  build-time checkout, and a live origin would pull unpatched upstream `main`. Updating means a
  newer image.
- **Gateway:** Hermes runs one gateway per host (here, per container), started from the root home
  and serving every profile; `hermes gateway run` under a named profile is refused (exit 78,
  "configuration error", so supervisors do not restart it). Apps start it with
  `HERMES_HOME=/root/.hermes hermes gateway run`. It serves the `android` profile from the
  profile's own settings and keys. The API server listens on the root home's settings, passed as
  process environment (`API_SERVER_ENABLED=true`, `API_SERVER_KEY` of at least 16 characters), and
  serves the profile at `:8642/p/android/v1` with the key in the profile's `.env`. The root home
  keeps only the gateway's runtime state (pid, locks, cron ticker), which an image upgrade may
  drop.
- **Size:** reported on every build (compressed and uncompressed). No limit yet; one is set after
  the first real build.

## 5. CI Workflow (`alpine-image.yml`)

1. **Triggers:** a daily schedule; manual dispatch (optionally naming an upstream tag or forcing a
   rebuild); pushes to `android` (a patch or Dockerfile change rebuilds the current release).
2. **Detect:** the stable release is upstream's GitHub "latest release"
   (`GET /repos/NousResearch/hermes-agent/releases/latest`: not a draft or prerelease; `v0.22.2` at
   design time). Its `tag_name` is the version. If GHCR already has that version built with the
   same build hash (the tag `<version>-p<hash>` exists), stop. The hash covers the patch series and
   the image recipe (`image/Dockerfile.alpine`, `image/profile.d/`), so a recipe change rebuilds. A
   run with nothing new takes seconds.
3. **Prepare:** clone upstream at the tag and apply `patches/` with `git am`. Any failure fails the
   run; nothing is published.
4. **Build:** Docker Buildx on the native arm64 runner, `linux/arm64`.
5. **Smoke test** (before any push), all with `docker run --network none`: the profile directory is
   empty and is `HERMES_HOME` in a login shell; `hermes --version` under the profile exits 0,
   prints the expected version and shows no dependency sync; the profile gets no `installs/`
   dependency state; no `.env` or `auth.json` exists under `/root` or `/etc` outside the Hermes
   checkout and dependency directories (which hold harmless bundled certificates). (`hermes
   doctor` is not used: its connectivity checks and missing-provider warnings would make an offline
   run flaky.)
6. **Publish:** push to `ghcr.io/oonid/hermes-agent` with the build tag `<version>-p<hash>` (the
   build hash of step 2; immutable unless a forced rebuild re-publishes it), plus `<version>` and
   `<version>-alpine<x.y>`, plus `latest` only when the version is upstream's current latest
   release (a manual rebuild of an older tag never moves `latest`). Authenticated by the
   workflow's `GITHUB_TOKEN`. The job summary records the tags, digest, sizes and the names of the
   applied patches.
7. **One-time manual step:** the package's visibility is set to public on GHCR, so phones can pull
   anonymously.

## 6. Testing

- In CI: the patch series applies to the target tag; the smoke tests above; a unit test for the
  release-detection script (stable tag found, already built, upstream unreachable).
- On a device, with the existing oonid/pr app (the dedicated app does not exist yet):
  1. Custom OCI image `ghcr.io/oonid/hermes-agent:<version>` with alias `hermes-img`; record the
     install time and size against the ~11-minute install-from-scratch baseline.
  2. In its terminal: `hermes --version` with no dependency sync, and `HERMES_HOME` is
     `/root/.hermes/profiles/android`.
  3. A gateway check as in oonid/pr PR #16: a provider configured in the profile's `.env`, the host
     gateway started as in §4, at least two requests to the profile's API (`/p/android/v1`)
     through `adb forward`, sessions saved under the profile, a CLI connection to the running
     gateway (the case the earlier WebSocket import fix addressed), then End drains it
     cleanly. The provider key goes on the phone only with the user's go-ahead and is removed
     afterwards.
  oonid/pr cannot bind-mount the profile, so in this check the data lives inside the container;
  the bind mount is the dedicated app's job.

## 7. Failure Handling

- A patch conflict, an upstream API error or a GHCR push error fails the run without publishing;
  the next daily run tries again.
- The smoke tests gate the push, so a broken image never becomes `latest`.
- Rollback is installing the previous version tag.

## 8. Out of Scope

The dedicated Android app (first-run setup, provider key entry, bind-mounting the profile,
gateway auto-start), amd64 images, optional extras (browser automation, TTS models, dashboard),
automatic syncing of the fork's `main`, and image signing (cosign).

## 9. Success Criteria

- A public `ghcr.io/oonid/hermes-agent` image is rebuilt automatically for each upstream stable
  release with the fork's patches.
- It installs on the phone through oonid/pr much faster than building Hermes on the phone.
- Hermes and its gateway work there under PRoot.

## 10. Revisions During Planning and Implementation

- User data moved from `/data/hermes` to the profile `/root/.hermes/profiles/android`: Hermes
  keeps its dependency environment under the data root, so an empty `/data/hermes` would have
  synced every dependency on the phone's first run. A profile shares its root's dependencies.
- The checkout is `/root/.hermes/hermes-agent` (the installer's default layout under the root),
  not `/opt/hermes`.
- The patch series starts empty (see §3).
- Builds carry a `<version>-p<hash>` tag (immutable unless a forced rebuild re-publishes it),
  which also implements the "already built" check. The hash covers the patch series and the image
  recipe (`image/Dockerfile.alpine`, `image/profile.d/`), so a recipe-only change rebuilds;
  `latest` moves only for upstream's current latest release.
- The smoke test checks for a dependency sync under the profile instead of running `hermes doctor`.
- The gateway runs from the root home and serves the profile (§4): v0.22.2 refuses a gateway of a
  named profile's own (exit 78). `--force` starts one but without the API server, which only the
  host listener serves; `gateway.standalone: true` is an upstream shim marked for removal.
- The image is built from a read-only bind mount of the prepared checkout's `.git`, cloned into
  place before the installer runs: copying the source left dead layers, and the installer's own
  blobless clone of a shallow checkout recursed until it ran out of file descriptors.
- The baked `.git` is repacked into one pack and the install-time telemetry receipt is removed;
  builds use `--provenance=false` so a containerd image store pushes a plain manifest.

## 11. Validation on a Phone

Pending: install the image through oonid/pr on a phone and confirm the §9 criteria there.
