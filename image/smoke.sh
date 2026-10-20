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

gw=$(run 'key=$(head -c16 /dev/urandom | od -An -tx1 | tr -d " \n")
printf "API_SERVER_ENABLED=true\nAPI_SERVER_KEY=%s\n" "$key" > /root/.hermes/.env
printf "API_SERVER_KEY=%s\n" "$key" > "$HERMES_HOME/.env"
HERMES_HOME=/root/.hermes hermes gateway run >/tmp/gw.log 2>&1 &
for i in $(seq 1 90); do curl -fs -m 2 http://127.0.0.1:8642/health && break; sleep 1; done
echo; hermes gateway status 2>&1' 2>&1 || true)
grep -q '"status": "ok"' <<<"$gw" || fail "the gateway API did not answer /health: $gw"
grep -q "default-profile multiplexer" <<<"$gw" || fail "the gateway does not serve the profile: $gw"

doctor=$(run 'hermes pm doctor 2>&1') || fail "hermes pm doctor found problems: $(grep '✗' <<<"$doctor" || echo "$doctor")"

variant=$(docker image inspect --format '{{ index .Config.Labels "io.github.oonid.hermes.variant" }}' "$image")
if [ -z "$variant" ] || [ "$variant" = full ]; then
    # upstream's install ships no precompiled bytecode: the first run may write it
    run 'hermes --version >/dev/null 2>&1; touch /tmp/mark; sleep 1; hermes --version >/dev/null 2>&1
test -z "$(find /root/.hermes/hermes-agent -name "*.pyc" -newer /tmp/mark | head -1)"' \
        || fail "a second run rewrote bytecode in the checkout"
else
    # an extractor that drops file times must not invalidate the bytecode
    run 'find /root/.hermes/hermes-agent /root/.hermes/tools /root/.hermes/installs -name "*.py" -exec touch -d 2001-01-01 {} +
touch /tmp/mark; sleep 1; hermes --version >/dev/null 2>&1
test -z "$(find /root/.hermes/hermes-agent /root/.hermes/tools /root/.hermes/installs -name "*.pyc" -newer /tmp/mark | head -1)"' \
        || fail "a run rewrote bytecode after the source file times changed"
fi

echo "SMOKE OK: $out"
