# Hermes Agent on Alpine for Android (PRoot)

This branch of `oonid/hermes-agent` builds `ghcr.io/oonid/hermes-agent`: Alpine Linux with Hermes
Agent preinstalled, for Android apps that run Linux containers under PRoot (no root, no VM). The
`main` branch mirrors upstream `NousResearch/hermes-agent` unchanged.

## The image

- Each upstream stable release, with the patches in `patches/` applied, built for `linux/arm64`.
- Two variants, `full` and `gateway` (the smaller one), each tagged `<version>` (e.g. `v0.22.2`)
  with a `-gateway` suffix for the slim one, plus `-alpine<x.y>`, an immutable build tag
  `<version>-p<hash>` (and `<version>-p<hash>-gateway`; the hash covers `patches/` and the image
  recipe: `image/Dockerfile.alpine`, `image/profile.d/` and `image/slim.sh`), and a moving tag for
  upstream's current release (`latest` or `gateway`).

| Variant | Tags | On the phone / download | Works | Not included |
|---------|------|-------------------------|-------|--------------|
| full | `<version>`, `<version>-alpine<x.y>`, `latest` | 1.7 GB / 622 MB | everything upstream installs | browser automation, computer use |
| gateway | `<version>-gateway`, `<version>-gateway-alpine<x.y>`, `gateway` | ~0.7 GB / ~265 MB (amd64 build) | the gateway and its API, every messaging platform, cron, `hermes` and `hermes -z`, the prebuilt TUI and dashboard | rebuilding the TUI or dashboard from source, the checkout's git history, debug symbols, Google APIs beyond the seven Hermes uses, tests |

- Hermes is installed by its own installer under `/root/.hermes`; browser automation and computer
  use are left out because they cannot run under PRoot on Android.
- Your data lives in the Hermes profile `/root/.hermes/profiles/android` (`HERMES_HOME`). It is
  empty in the image and reuses the image's dependencies, so an app can keep it outside the
  container and swap in a newer image without losing it.
- No keys or personal settings are in the image.

## Use it with oonid/pr

In the oonid/pr app, open **Custom OCI image**, enter `ghcr.io/oonid/hermes-agent:latest` with an
alias such as `hermes-img`, and install. `ghcr.io/oonid/hermes-agent:gateway` is the smaller
choice. Open the container, then configure a model provider in
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
`http://127.0.0.1:8642/p/android/v1`. The profile is served once its `.env` is not empty; an empty
profile directory does not count.

Updating Hermes means installing a newer image; `hermes update` does not work inside the
container.

## How it is built

`.github/workflows/alpine-image.yml` checks upstream daily (and on a push to this branch or a
manual run). For a release and build hash (patches plus the image recipe) with a variant not yet
published it clones the release, applies `patches/` (`image/prepare.sh`), then for each missing
variant builds `image/Dockerfile.alpine` on GitHub's arm64 runner (`image/build.sh`), runs an
offline smoke test (`image/smoke.sh`), and only then pushes. The build hash leaves out
`image/build.sh`, `image/smoke.sh` and the workflow, so a change to one of those alone needs a
manual run with `force`.

Local build and test (any architecture; `linux/amd64` is fine on a PC):

    image/prepare.sh https://github.com/NousResearch/hermes-agent.git v0.22.2 patches work/src
    image/build.sh work/src v0.22.2 local full linux/amd64 hermes-alpine:test
    image/build.sh work/src v0.22.2 local gateway linux/amd64 hermes-alpine:test-gateway
    image/smoke.sh hermes-alpine:test v0.22.2
    image/smoke.sh hermes-alpine:test-gateway v0.22.2
    python3 -m unittest discover -s image/tests -v

Designs: `docs/design/alpine-image.md`, `docs/design/alpine-image-variants.md`. Plans:
`docs/plans/alpine-image.md`, `docs/plans/alpine-image-variants.md`.
