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

shopt -s nullglob
series=("$patches"/*.patch)
if [ ${#series[@]} -gt 0 ]; then
    if ! git -C "$out" -c user.name="hermes image build" -c commit.gpgsign=false \
            -c user.email="hermes-image-build@example.invalid" \
            am --quiet "${series[@]}"; then
        git -C "$out" am --abort || true
        echo "a patch in $patches does not apply to $tag" >&2
        exit 1
    fi
fi
git -C "$out" rev-parse HEAD
