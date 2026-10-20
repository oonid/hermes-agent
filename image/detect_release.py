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
VARIANTS = ("full", "gateway")
RECIPE = ("image/Dockerfile.alpine", "image/profile.d", "image/slim.sh")


def _recipe_files(recipe):
    files = set()
    for entry in recipe:
        path = Path(entry)
        if path.is_dir():
            files.update(p.as_posix() for p in path.rglob("*") if p.is_file())
        elif path.is_file():
            files.add(path.as_posix())
        else:
            raise FileNotFoundError(f"recipe path not found: {entry}")
    return sorted(files)


def patch_hash(patch_dir: Path, recipe=()) -> str:
    """Hash the patch series, then the image recipe files, so either change rebuilds."""
    digest = hashlib.sha256()
    for patch in sorted(Path(patch_dir).glob("*.patch")):
        digest.update(patch.name.encode())
        digest.update(b"\0")
        digest.update(patch.read_bytes())
        digest.update(b"\0")
    for name in _recipe_files(recipe):
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(Path(name).read_bytes())
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


def variant_tag(build_tag, variant):
    return build_tag if variant == "full" else f"{build_tag}-{variant}"


def decide(image, patch_dir, tag=None, force=False, fetch=None, exists=None,
           recipe=()):
    latest = latest_release(fetch)
    version = tag or latest
    phash = patch_hash(patch_dir, recipe)
    build_tag = f"{version}-p{phash}"
    has = exists or image_exists
    variants = [v for v in VARIANTS if force or not has(f"{image}:{variant_tag(build_tag, v)}")]
    return {"version": version, "patch_hash": phash, "build_tag": build_tag,
            "build": bool(variants), "variants": variants, "is_latest": version == latest}


def _format(value):
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, list):
        return json.dumps(value, separators=(",", ":"))
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--patches", default="patches")
    parser.add_argument("--tag", default="")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    result = decide(args.image, Path(args.patches), args.tag or None, args.force,
                    recipe=RECIPE)
    lines = [f"{key}={_format(value)}" for key, value in result.items()]
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
