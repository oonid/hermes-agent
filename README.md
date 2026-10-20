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
API_SERVER_ENABLED=true API_SERVER_KEY=<16+ characters> HERMES_HOME=/root/.hermes hermes gateway run
```

With `API_SERVER_KEY` (16+ characters) also in `$HERMES_HOME/.env`, the profile's OpenAI-compatible
API is at `http://127.0.0.1:8642/p/android/v1`.

Updating Hermes means installing a newer image; `hermes update` does not work inside the
container.

## How it is built

`.github/workflows/alpine-image.yml` checks upstream daily (and on a push to this branch or a
manual run). For a release and build hash (patches plus the image recipe) not yet published it
clones the release, applies `patches/` (`image/prepare.sh`), builds `image/Dockerfile.alpine` on
GitHub's arm64 runner (`image/build.sh`), runs an offline smoke test (`image/smoke.sh`), and only
then pushes. A change to `image/build.sh` alone is not in the build hash; it needs a manual run
with `force`.

Local build and test (any architecture; `linux/amd64` is fine on a PC):

    image/prepare.sh https://github.com/NousResearch/hermes-agent.git v0.22.2 patches work/src
    image/build.sh work/src v0.22.2 local linux/amd64 hermes-alpine:test
    image/smoke.sh hermes-alpine:test v0.22.2
    python3 -m unittest discover -s image/tests -v

Design: `docs/design/alpine-image.md`. Plan: `docs/plans/alpine-image.md`.
