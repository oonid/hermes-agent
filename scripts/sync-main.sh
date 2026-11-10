#!/usr/bin/env bash
# Fast-forward this fork's `main` to upstream's `main`.
#
# GitHub's "Sync fork" button targets the default branch, `android`, which shares no history with
# upstream, so it reports conflicts. `main` has no commits of its own and only ever fast-forwards.
# Upstream's `main` carries workflows that run on a push to `main` (docker, deploy-site,
# js-autofix, ...), so Actions is paused around the push, and anything that still starts or gets
# registered is cancelled or disabled afterwards. Only alpine-image.yml stays enabled.
#
# Usage: scripts/sync-main.sh [--check]    (--check reports and changes nothing)
set -euo pipefail

FORK=oonid/hermes-agent
UPSTREAM=NousResearch/hermes-agent
KEEP=.github/workflows/alpine-image.yml
SETTLE=10

check=false
case "${1:-}" in
    --check) check=true ;;
    "") ;;
    *) echo "usage: $0 [--check]" >&2; exit 2 ;;
esac

cd "$(git rev-parse --show-toplevel)"
git fetch --quiet "git@github.com:$UPSTREAM.git" main:refs/remotes/upstream/main
git fetch --quiet "git@github.com:$FORK.git" main:refs/remotes/fork/main
up=$(git rev-parse refs/remotes/upstream/main)
fork=$(git rev-parse refs/remotes/fork/main)

if [ "$up" = "$fork" ]; then
    echo "main is up to date at ${up:0:10}"
    exit 0
fi
if ! git merge-base --is-ancestor "$fork" "$up"; then
    echo "fork main ${fork:0:10} is not an ancestor of upstream main ${up:0:10}; not touching it" >&2
    exit 1
fi
echo "main is $(git rev-list --count "$fork..$up") commits behind upstream (${fork:0:10} -> ${up:0:10})"
$check && exit 0

allowed=$(gh api "repos/$FORK/actions/permissions" --jq .allowed_actions)
restore() {
    sleep "$SETTLE"
    gh api -X PUT "repos/$FORK/actions/permissions" -F enabled=true -f allowed_actions="$allowed" >/dev/null
    echo "Actions re-enabled (allowed_actions=$allowed)"
}
gh api -X PUT "repos/$FORK/actions/permissions" -F enabled=false >/dev/null
trap restore EXIT
echo "Actions paused"

git push "git@github.com:$FORK.git" "$up:refs/heads/main"

trap - EXIT
restore

sleep "$SETTLE"
for id in $(gh run list -R "$FORK" --branch main --limit 50 --json databaseId,headSha,status \
        --jq ".[] | select(.headSha == \"$up\" and .status != \"completed\") | .databaseId"); do
    gh run cancel -R "$FORK" "$id" >/dev/null && echo "cancelled run $id"
done
for path in $(gh api "repos/$FORK/actions/workflows" --paginate \
        --jq ".workflows[] | select(.state == \"active\" and .path != \"$KEEP\") | .path"); do
    gh workflow disable -R "$FORK" "$(basename "$path")" && echo "disabled $path"
done
echo "main is now ${up:0:10}"
