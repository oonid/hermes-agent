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
    -exec sh -c 'for f; do if head -c4 "$f" | grep -q ELF; then strip --strip-unneeded "$f" || exit 1; fi; done' sh {} +
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
"$PY" -I -m compileall -q -j0 -f --invalidation-mode checked-hash -l . >/dev/null
"$PY" -I -m compileall -q -j0 -f --invalidation-mode checked-hash \
    acp_adapter agent cron gateway hermes_cli hermes_platform plugins pm providers tools tui_gateway >/dev/null
"$PY" -I -m compileall -q -j0 -f --invalidation-mode checked-hash -x '/(test|tests|idlelib|tkinter|turtledemo)/' \
    "$(dirname "$(dirname "$PY")")"/lib/python3.* >/dev/null
"$PY" -I -m compileall -q -f -j0 --invalidation-mode checked-hash "$SP" >/dev/null
for d in "$H"/installs/*/pm-runtime; do
    [ -d "$d" ] && "$PY" -I -m compileall -q -f -j0 --invalidation-mode checked-hash "$d" >/dev/null
done

rm -rf /root/.cache /root/.npm /tmp/* /var/cache/apk/*
