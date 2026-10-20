#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 6 ]; then
    echo "usage: $0 <src-dir> <version> <patch-hash> <variant> <platform> <image-ref>..." >&2
    exit 2
fi
src=$(cd "$1" && pwd) version=$2 phash=$3 variant=$4 platform=$5
shift 5
here=$(cd "$(dirname "$0")" && pwd)
commit=$(git -C "$src" rev-parse HEAD)
revision=$(git -C "$here" rev-parse HEAD 2>/dev/null || echo unknown)

tags=()
for ref in "$@"; do tags+=(-t "$ref"); done

docker buildx build --platform "$platform" --load --provenance=false \
    --build-context srcgit="$src/.git" \
    --build-arg HERMES_COMMIT="$commit" \
    --build-arg HERMES_VERSION="$version" \
    --build-arg FORK_REVISION="$revision" \
    --build-arg PATCH_HASH="$phash" \
    --build-arg VARIANT="$variant" \
    -f "$here/Dockerfile.alpine" "${tags[@]}" "$here"
