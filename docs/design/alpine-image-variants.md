# Alpine Hermes Image Variants

**Date:** 2026-10-20
**Status:** implemented; validation on a phone pending (§9)
**Builds on:** `docs/design/alpine-image.md` (the full image, validated on a phone in its §11)

## 1. Goal

Offer smaller variants of `ghcr.io/oonid/hermes-agent` next to the full image, each documented with
what it keeps and what it drops, starting with the smallest variant that still runs Hermes as
normal. The full image is 1.70 GB on the phone and a 622 MB download; most of that is build
tooling, debug symbols, duplicate runtimes and files nothing reads at run time.

Further variants (a larger rung, or a smaller one if upstream gains a Node-free mode) follow the
same mechanism later.

## 2. Decisions

| Topic | Decision |
|-------|----------|
| Variants | `full` (today's image, unchanged) and `gateway` (all safe cuts); a ladder that can grow later |
| Naming | One package, tag suffixes: `gateway` gets `<version>-gateway`, `<version>-gateway-alpine<x.y>`, `gateway`, and the immutable `<version>-p<hash>-gateway`; `full` keeps `<version>`, `<version>-alpine<x.y>`, `latest` and `<version>-p<hash>` |
| Node | Kept (stripped, without headers) in `gateway`: Hermes has no supported Node-free install, and without Node every command warns "install out of sync" and the TUI, the dashboard chat, the WhatsApp bridge and `npx` MCP servers stop working |
| `.git` | Removed in `gateway` |
| Bytecode | Precompiled in `gateway` |
| Build approach | One Dockerfile with `ARG VARIANT`; `image/slim.sh <variant>` runs in the same `RUN` as the installer (a later `RUN` cannot shrink the image) |

## 3. What Each Variant Contains

**`full`:** exactly what `docs/design/alpine-image.md` §4 describes.

**`gateway`:** the same contract (§4 of that design: login shell, profile
`/root/.hermes/profiles/android`, gateway from the root home), with these cuts:

| Cut | Saves (arm64, uncompressed) |
|-----|------|
| Strip debug symbols from the managed Python, libpython, Node, uv and ripgrep binaries and the venv's native extensions; then refresh the tool digests Hermes records in `tools/facts.json` | ~230 MB |
| `hermes pm gc`, and delete uv's bootstrap CPython under `/root/.local/share/uv/python` (used only by the installer) | ~79 MB |
| Node's `include/` (only native add-on builds read it) | ~58 MB |
| Every `node_modules` (the TUI and dashboard ship prebuilt; the modules only rebuild them) | ~342 MB |
| Checkout files nothing reads at run time: `tests/`, `tests-js/`, `apps/desktop/`, `evals/`, `contributors/`, `.github/`, and `website/` except `static/api` (`apps/shared` stays: the TUI and dashboard freshness checks read it) | ~124 MB |
| Google API discovery documents except the seven Hermes's Google features build (gmail v1, calendar v3, drive v3, docs v1, sheets v4, people v1, chat v1) | ~92 MB |
| `.git` of the checkout | ~86 MB |
| Precompiled bytecode for the checkout, the Python standard library and the venv, forced to `checked-hash` so it stays valid when an extractor does not keep file times | adds ~67 MB |

Expected result: about 0.7 GB on the phone and, measured on an amd64 build, about 265 MB to
download (arm64 recorded after the first CI build).

**Works in `gateway`:** the gateway and its API server, every messaging platform including the
WhatsApp bridge, cron, the plain `hermes` CLI and `hermes -z`, the prebuilt TUI (`hermes --tui`)
and dashboard, `hermes doctor` and `hermes pm doctor`, MCP servers run with `npx` (they download
their packages when first used).

**Not in `gateway`:** rebuilding the TUI or dashboard from source (needs a full `npm ci` with
network), the install method reported as `git` (it reads `unknown`; updating is by a newer image
in every variant), debug symbols for native crash backtraces, Google APIs beyond the seven above,
and Hermes's own test suite.

Not cut, after investigation: the venv's `workspace/` source snapshot (about 44 MB; Hermes's
environment repair may read it) and `nemo_relay` (a core dependency).

## 4. Build

- `image/Dockerfile.alpine` gains `ARG VARIANT=full`. In the installer's `RUN`, after the existing
  cleanup, `image/slim.sh "$VARIANT"` runs from a read-only bind mount of the build context, so
  the script adds no layer. For `full` it does nothing, so the full image is built exactly as now.
- `image/slim.sh <full|gateway>` holds the cuts of §3, fails on an unknown variant, and fails
  loudly if any step fails.
- `image/build.sh` takes the variant and passes it as a build argument; the OCI labels gain the
  variant (`io.github.oonid.hermes.variant`).
- The build hash also covers `image/slim.sh`, so a change to the cuts rebuilds every variant.

## 5. Smoke Test

`image/smoke.sh <image-ref> <version>` keeps its checks and, for every variant, adds:

- The gateway started from the root home (listener settings in `/root/.hermes/.env`) answers
  `/health`, and `hermes gateway status` in the profile shows the multiplexer serving it. The
  check writes an `API_SERVER_KEY` to the profile `.env` inside its throwaway container (an empty
  profile does not count as one).
- `hermes pm doctor` reports no problem (catches stale tool digests after stripping).
- Bytecode: for `full` (or no variant label), a second `hermes --version` writes no new bytecode
  under the checkout; for the other variants, no run writes bytecode, even after the file time of
  every source changes (catches precompiled files that Python would rewrite).

All of it runs with `--network none`, as now.

## 6. CI

- The build job runs once per variant (a matrix over `full` and `gateway`), in parallel on the
  arm64 runner; each variant is built, smoke-tested and only then published with its tags (§2).
- The 'already built' check stays per release and build hash, and builds only the variants whose
  immutable tag is missing, so a variant that failed is retried and a published one is never
  rebuilt unless forced.
- The job summary records each variant's tags, digest and sizes.

## 7. Testing

- In CI: the smoke test for each variant; the unit tests as now (the detect script's hash covers
  `image/slim.sh`).
- On a phone, with oonid/pr: install `ghcr.io/oonid/hermes-agent:<version>-gateway` as a Custom OCI
  image; record install time, download and size; then the checks of
  `docs/design/alpine-image.md` §11: first run time, the gateway from the root home with two API
  requests and a CLI request, and End. Results go in §9 of this design.

## 8. Out of Scope

A Node-free variant (needs an upstream install mode or a fork patch), a variant with extra
features (browser automation, TTS), trimming the venv's `workspace/`, amd64 images, and making
`gateway` the default `latest`.

## 9. Validation on a Phone

Pending.
