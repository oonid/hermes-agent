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
